from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typing import Optional

from app.setup.database import get_db
from app.models.migration import (
    Policies, Clients, Mandate, PaymentHistory, CallBackPayments,
    MandateCallback, UniwalletCallback, MandateTransactionCallback, PaymentCredit,
)
from app.schemas.ussd_schemas import *
from app.config.addition import (
    make_mandate_payment, make_one_time_payment,
    get_mandate_details, check_uniwallet_transaction_status, send_sms,
)

router = APIRouter(prefix="/ussd/payments")


# ============= Shared helpers =============

async def create_mandate_record(
    client_phone: str,
    amount_to_debit: str,
    frequency_type: str,
    frequency: str,
    start_date: str,
    end_date: str,
    debit_day: str,
    ref_no: str,
    db: Session,
) -> dict:
    """Call Transflow and persist the resulting Mandate row (best-effort).
    Used by POST /payments/mandate -- purchase no longer starts a mandate itself."""
    try:
        mandate_response = await make_mandate_payment(
            client_phone=client_phone, amount_to_debit=amount_to_debit,
            frequency_type=frequency_type, frequency=frequency,
            start_date=start_date, end_date=end_date, debit_day=debit_day, ref_no=ref_no,
        )
        mandate_record = Mandate(
            client_id=client_phone,
            responseCode=mandate_response.get("responseCode", "0000"),
            responseMessage=mandate_response.get("responseMessage", "Success"),
            merchantId=mandate_response.get("merchantId", ""),
            productId=mandate_response.get("productId", ""),
            mandateId=mandate_response.get("mandateId", ""),
            clientPhone=client_phone, thirdPartyReferenceNo=ref_no,
        )
        db.add(mandate_record)
        db.commit()

        return {
            "status": "success",
            "mandate_id": mandate_response.get("mandateId"),
            "response_code": mandate_response.get("responseCode"),
            "response_message": mandate_response.get("responseMessage"),
        }
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": f"Mandate creation failed: {str(e)}"}


# A cancelled policy is terminated for good -- a re-application is a new registration --
# so no payment or callback may ever move it (or an expired one) back to Active.
NON_CREDITABLE_STATUSES = ('Cancelled', 'Expired')


def credit_policy(db: Session, policy: Policies, transaction_id: str, amount: float, payment_method: str) -> bool:
    """Record a payment against a policy and activate it if it isn't already. The caller commits.
    Returns False without touching anything if the policy is Cancelled/Expired."""
    if policy.Status in NON_CREDITABLE_STATUSES:
        return False

    existing = db.query(PaymentHistory).filter(PaymentHistory.transaction_id == transaction_id).first()
    if not existing:
        db.add(PaymentHistory(
            policy_id=policy.PolicyID, amount=amount,
            currency="GHS", payment_method=payment_method,
            transaction_id=transaction_id, status="Success",
        ))
    if policy.Status != 'Active':
        policy.Status = 'Active'
    return True


def _phone_key(phone: Optional[str]) -> str:
    # Compare the last 9 digits so 0244123456, 233244123456 and +233244123456 all match.
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return digits[-9:]


def _sms_number(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    return "233" + digits[1:] if digits.startswith("0") else digits


def _resolve_policy_number(ref_no: str) -> str:
    # A one-time-payment ref may carry a duplicate-retry suffix (e.g. "POL123_4567") --
    # the underlying policy number is always the part before the first underscore.
    return ref_no.split("_")[0]


# ============= Mandate =============

@router.post("/mandate", response_model=MandateResponse)
async def create_mandate(payload: MandateCreateRequest, db: Session = Depends(get_db)):
    """Direct mandate creation against Transflow. Honors the caller's own schedule
    (frequency/start/end/debit day) rather than the purchase flow's fixed defaults."""
    result = await create_mandate_record(
        client_phone=payload.client_phone, amount_to_debit=payload.amount_to_debit,
        frequency_type=payload.frequency_type, frequency=payload.frequency,
        start_date=payload.start_date, end_date=payload.end_date,
        debit_day=payload.debit_day, ref_no=payload.ref_no, db=db,
    )
    return MandateResponse(
        status=result["status"],
        message=result.get("message", "Mandate request submitted"),
        mandate_id=result.get("mandate_id"),
        response_code=result.get("response_code"),
        response_message=result.get("response_message"),
    )


@router.get("/mandate/{phone_number}", response_model=MandateDetailsResponse)
async def mandate_details(phone_number: str, date: Optional[str] = None):
    """Single-call mandate details lookup from Transflow. Pure read, no DB writes --
    the DB-writing 'activate on lookup' side effect lives on the mandate-transaction
    callback webhook instead (see POST /callbacks/mandate-transaction)."""
    result = await get_mandate_details(phone_number, date)
    return MandateDetailsResponse(
        message="Mandate records found" if result["found"] else "No mandate records found",
        found=result["found"], data=result["data"],
    )


# ============= One-time payment =============

@router.post("/one-time", response_model=OneTimePaymentResponse)
async def one_time_payment(payload: OneTimePaymentRequest):
    """Direct one-time debit via Uniwallet. No DB writes here -- activation happens
    via GET /one-time/{ref_no}/status or the Uniwallet callback webhook."""
    result = await make_one_time_payment(
        msisdn=payload.msisdn, amount=payload.amount, network=payload.network,
        currency=payload.currency, ref_no=payload.ref_no,
    )
    return OneTimePaymentResponse(
        status="success", ref_no=result["refNo"],
        message="Payment request submitted", data=result.get("data"),
    )


@router.get("/one-time/{ref_no}/status", response_model=OneTimeStatusResponse)
async def one_time_payment_status(ref_no: str, db: Session = Depends(get_db)):
    """Single-shot status check against Uniwallet (replaces the old blocking
    10x3s poll loop -- the caller re-polls this endpoint on their own schedule
    instead of the server blocking a worker thread)."""
    data = await check_uniwallet_transaction_status(ref_no)
    response_code = data.get("responseCode")

    if response_code == "01":
        policy_number = _resolve_policy_number(ref_no)
        policy = db.query(Policies).filter(Policies.PolicyNumber == policy_number).first()

        if policy:
            was_active = policy.Status == 'Active'
            credited = credit_policy(
                db, policy, transaction_id=ref_no,
                amount=float(data.get("amount", 0) or 0), payment_method="One-time-payment",
            )

            db.add(CallBackPayments(
                client_id=policy.ClientCode,
                uniwalletTransactionId=data.get("uniwalletTransactionId"),
                networkTransactionId=data.get("networkTransactionId"),
                refNo=data.get("refNo", ref_no),
                productId=data.get("productId"),
                msisdn=data.get("msisdn"),
                amount=data.get("amount"),
                narration=data.get("narration"),
                timestamp=data.get("timestamp"),
                responseCode=response_code,
                responseMessage=data.get("responseMessage"),
                network=data.get("network"),
                transflowId=data.get("transflowId"),
            ))
            db.commit()

            if not credited:
                return OneTimeStatusResponse(
                    status="success", data=data,
                    message=f"Payment succeeded but policy is {policy.Status}; it was not reactivated.",
                )
            return OneTimeStatusResponse(
                status="success", message="Policy is active now.",
                policy_activated=not was_active, data=data,
            )

        return OneTimeStatusResponse(status="success", message="Payment succeeded but no matching policy was found.", data=data)

    if response_code == "02":
        return OneTimeStatusResponse(status="pending", message="Payment still processing.", data=data)

    return OneTimeStatusResponse(status="failed", message="Payment failed or could not be confirmed.", data=data)


# ============= Payment gateway webhook receivers =============

@router.post("/callbacks/mandate", response_model=CallbackAck)
async def mandate_callback(payload: MandateCallbackCreate, db: Session = Depends(get_db)):
    """Transflow mandate webhook -- persists every callback, activates the matching
    policy when the mandate is confirmed successful (responseCode '01')."""
    db.add(MandateCallback(**payload.dict()))
    db.commit()

    if payload.responseCode == "01":
        policy = db.query(Policies).filter(Policies.PolicyNumber == payload.thirdPartyReferenceNo).first()
        if policy and policy.Status != 'Active' and policy.Status not in NON_CREDITABLE_STATUSES:
            policy.Status = 'Active'
            db.commit()

    return CallbackAck(responseCode=payload.responseCode, responseMessage=payload.responseMessage)


@router.post("/callbacks/uniwallet")
async def uniwallet_callback(payload: UniwalletCallbackCreate, db: Session = Depends(get_db)):
    """Uniwallet webhook -- straight passthrough persistence, no policy side effect
    (matches the source behavior this was ported from)."""
    record = UniwalletCallback(**payload.dict())
    db.add(record)
    db.commit()
    db.refresh(record)
    return payload


@router.post("/callbacks/mandate-transaction", response_model=CallbackAck)
async def mandate_transaction_callback(payload: MandateTransactionCallbackCreate, db: Session = Depends(get_db)):
    """Transflow recurring-debit-transaction webhook -- persists every callback,
    activates the matching policy and records PaymentHistory when the debit is
    confirmed successful (responseCode '01')."""
    db.add(MandateTransactionCallback(**payload.dict()))
    db.commit()

    if payload.responseCode == "01":
        policy = db.query(Policies).filter(Policies.PolicyNumber == payload.thirdPartyReferenceNo).first()
        if policy:
            # Each recurring debit has its own transaction id. The policy number is shared by
            # every debit, so keying on it recorded only the first month's payment.
            transaction_id = (
                payload.debitOrderTransactionId or payload.momTransactionId or payload.thirdPartyReferenceNo
            )
            credit_policy(
                db, policy, transaction_id=transaction_id,
                amount=float(payload.amount or 0), payment_method="Mandate-payment",
            )
            db.commit()

    return CallbackAck(responseCode=payload.responseCode, responseMessage=payload.responseMessage)


# ============= Payment crediting (IT Consortium -> us) =============

@router.post("/credit", response_model=PaymentCreditResponse)
async def credit_payment(payload: PaymentCreditRequest, db: Session = Depends(get_db)):
    """Receive a payment notification, store it in payment_credits and credit the policy.
    Kept separate from registration/purchase so recurring debits and one-time payments can
    credit a policy at any time after it's created. Idempotent on transactionId: re-sending an
    already-credited transaction changes nothing and returns duplicate=true."""
    record = db.query(PaymentCredit).filter(PaymentCredit.transaction_id == payload.transactionId).first()
    if record and record.status == "credited":
        policy = db.query(Policies).filter(Policies.PolicyID == record.policy_id).first()
        return PaymentCreditResponse(
            status="credited", message="Transaction already credited",
            transactionId=record.transaction_id, policyNumber=record.policy_number,
            amount=float(record.amount), policyStatus=policy.Status if policy else None, duplicate=True,
        )

    policy = db.query(Policies).filter(Policies.PolicyNumber == payload.policyNumber).first()
    note = None
    http_status = 200
    if not policy:
        status, note, http_status = "rejected", "Policy not found", 404
    elif not credit_policy(
        db, policy, transaction_id=payload.transactionId, amount=payload.amount, payment_method="Payment-credit",
    ):
        status, http_status = "rejected", 409
        note = f"Policy is {policy.Status}; payment not applied -- needs refund or reallocation"
    else:
        status = "credited"
        client = db.query(Clients).filter(Clients.ClientCode == policy.ClientCode).first()
        if client and _phone_key(client.PhoneNumber) != _phone_key(payload.phoneNumber):
            note = "Payer phone differs from the policy holder's phone"

    # A rejected transaction may be re-sent once the problem is fixed, so reuse its row.
    if not record:
        record = PaymentCredit(transaction_id=payload.transactionId)
        db.add(record)
    record.policy_number = payload.policyNumber
    record.policy_id = policy.PolicyID if policy else None
    record.amount = payload.amount
    record.phone_number = payload.phoneNumber
    record.trans_date = payload.transDate
    record.status = status
    record.note = note

    try:
        db.commit()
    except IntegrityError:
        # The same transactionId arrived twice at the same moment; the other request stored it.
        db.rollback()
        return PaymentCreditResponse(
            status="credited", message="Transaction already received",
            transactionId=payload.transactionId, policyNumber=payload.policyNumber,
            amount=payload.amount, duplicate=True,
        )

    if status == "credited":
        message = "Payment credited successfully" + (f" ({note})" if note else "")
    else:
        message = note
    response = PaymentCreditResponse(
        status=status, message=message,
        transactionId=payload.transactionId, policyNumber=payload.policyNumber,
        amount=payload.amount, policyStatus=policy.Status if policy else None,
    )
    if status != "credited":
        return JSONResponse(status_code=http_status, content=response.dict())

    try:
        await send_sms(
            _sms_number(payload.phoneNumber),
            f"Payment of GHS {payload.amount:.2f} received for policy {payload.policyNumber}. "
            f"Ref: {payload.transactionId}. Thank you for choosing Equity Health Insurance.",
        )
    except Exception:
        pass  # the credit is already saved; a failed SMS must not fail the notification

    return response


# ============= Callback audit lists =============

@router.get("/callbacks/mandate")
async def list_mandate_callbacks(db: Session = Depends(get_db)):
    rows = db.query(MandateCallback).order_by(MandateCallback.id.desc()).limit(100).all()
    return [
        {
            "id": r.id, "responseCode": r.responseCode, "responseMessage": r.responseMessage,
            "merchantId": r.merchantId, "productId": r.productId, "mandateId": r.mandateId,
            "clientPhone": r.clientPhone, "thirdPartyReferenceNo": r.thirdPartyReferenceNo,
            "create_at": r.create_at.isoformat() if r.create_at else None,
        }
        for r in rows
    ]


@router.get("/callbacks/uniwallet")
async def list_uniwallet_callbacks(db: Session = Depends(get_db)):
    rows = db.query(UniwalletCallback).order_by(UniwalletCallback.id.desc()).limit(100).all()
    return [
        {
            "id": r.id, "uniwalletTransactionId": r.uniwalletTransactionId,
            "networkTransactionId": r.networkTransactionId, "refNo": r.refNo,
            "productId": r.productId, "msisdn": r.msisdn, "amount": r.amount,
            "narration": r.narration, "timestamp": r.timestamp, "responseCode": r.responseCode,
            "responseMessage": r.responseMessage, "network": r.network, "transflowId": r.transflowId,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
