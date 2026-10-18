"""How a policy is paid: by bank, or through the Controller (government payroll deduction).
Each policy has one Active method; setting a new one marks the old one Replaced."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.setup.database import get_db
from app.models.migration import Clients, Policies, PolicyPaymentMethod
from app.schemas.ussd_schemas import (
    BankDetails, ControllerDetails, PaymentMethodRequest, PaymentMethodOut, PaymentMethodResponse,
    PaymentMethodHistoryResponse,
)

router = APIRouter(prefix="/ussd")

CLOSED_STATUSES = ("Cancelled", "Expired")


def _holder_policy(db: Session, phone_number: str, policy_number: str):
    """(holder, policy), checking the policy belongs to this phone number."""
    holder = db.query(Clients).filter(Clients.PhoneNumber == phone_number).first()
    if not holder:
        raise HTTPException(status_code=404, detail="Client not found")
    policy = db.query(Policies).filter(
        Policies.PolicyNumber == policy_number, Policies.ClientCode == holder.ClientCode,
    ).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found for this phone number")
    return holder, policy


def method_out(m: PolicyPaymentMethod) -> PaymentMethodOut:
    return PaymentMethodOut(
        payment_mode=m.payment_mode, status=m.status, client_code=m.client_code, client_name=m.client_name,
        phone_number=m.phone_number, ghana_card=m.ghana_card, policy_number=m.policy_number,
        product_name=m.product_name, premium=float(m.premium) if m.premium is not None else None,
        frequency=m.frequency,
        bank=BankDetails(bank_name=m.bank_name, branch=m.bank_branch, account_name=m.account_name,
                         account_number=m.account_number) if m.payment_mode == "bank" else None,
        controller=ControllerDetails(staff_id=m.staff_id, employer=m.employer,
                                     management_unit=m.management_unit) if m.payment_mode == "controller" else None,
        set_at=m.created_at, replaced_at=m.replaced_at,
    )


def save_payment_method(db: Session, holder: Clients, policy: Policies, choice) -> PaymentMethodResponse:
    """Make `choice` the policy's Active payment method, keeping any previous one as Replaced.
    Used by the USSD endpoint below and the admin page."""
    if policy.Status in CLOSED_STATUSES:
        raise HTTPException(status_code=409, detail=f"This policy is {policy.Status}; its payment method can't be set")

    bank, controller = choice.bank, choice.controller
    row = PolicyPaymentMethod(
        policy_id=policy.PolicyID, payment_mode=choice.payment_mode, status="Active",
        client_code=holder.ClientCode,
        client_name=" ".join(p for p in (holder.FirstName, holder.OtherNames, holder.LastName) if p) or None,
        phone_number=holder.PhoneNumber, ghana_card=holder.NationalIDNumber,
        policy_number=policy.PolicyNumber, product_name=policy.Name, premium=policy.Premium,
        frequency=policy.PaymentFrequency,
        bank_name=bank.bank_name if bank else None, bank_branch=bank.branch if bank else None,
        account_name=bank.account_name if bank else None, account_number=bank.account_number if bank else None,
        staff_id=controller.staff_id if controller else None, employer=controller.employer if controller else None,
        management_unit=controller.management_unit if controller else None,
    )

    previous = db.query(PolicyPaymentMethod).filter(
        PolicyPaymentMethod.policy_id == policy.PolicyID, PolicyPaymentMethod.status == "Active",
    ).all()
    try:
        for old in previous:
            old.status = "Replaced"
            old.replaced_at = datetime.now()
        db.add(row)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Saving the payment method failed: {str(e)}")

    mode = "bank" if choice.payment_mode == "bank" else "Controller (payroll deduction)"
    return PaymentMethodResponse(
        status="success",
        message=f"{policy.PolicyNumber} will be paid by {mode}." + (" The previous method was replaced." if previous else ""),
        payment_method=method_out(row),
    )


@router.post("/payment-method", response_model=PaymentMethodResponse)
async def set_payment_method(payload: PaymentMethodRequest, db: Session = Depends(get_db)):
    """Set how a policy will be paid. The client and policy details are stored with it. If the
    policy already has a method, that one is kept on record as Replaced."""
    holder, policy = _holder_policy(db, payload.phone_number, payload.policy_number)
    return save_payment_method(db, holder, policy, payload)


@router.get("/payment-method", response_model=PaymentMethodHistoryResponse)
async def get_payment_method(phone_number: str, policy_number: str, db: Session = Depends(get_db)):
    """A policy's current payment method and the ones it replaced, newest first."""
    _, policy = _holder_policy(db, phone_number, policy_number)
    rows = db.query(PolicyPaymentMethod).filter(
        PolicyPaymentMethod.policy_id == policy.PolicyID,
    ).order_by(PolicyPaymentMethod.id.desc()).all()
    current = next((r for r in rows if r.status == "Active"), None)
    return PaymentMethodHistoryResponse(
        policy_number=policy.PolicyNumber,
        current=method_out(current) if current else None,
        history=[method_out(r) for r in rows if r is not current],
    )
