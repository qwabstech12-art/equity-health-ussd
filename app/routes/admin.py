"""Admin views over the database, used by the /admin page. Every route reads only, except
POST /payment-method, which lets staff change a policy's payment method."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.setup.database import get_db
from app.schemas.ussd_schemas import AdminPaymentMethodRequest, PaymentMethodResponse
from app.routes.payment_methods import save_payment_method
from app.models.migration import (
    Clients, Policies, PaymentHistory, PaymentCredit, PoliciesDependant, PolicyFamilyPlan, PolicyFamilyMember,
    PolicyPaymentMethod,
)

router = APIRouter(prefix="/admin")

PAID_STATUSES = ("Success", "completed")


def _iso(value):
    return value.isoformat() if value is not None else None


def _num(value):
    return float(value) if value is not None else None


def _page(query, page: int, size: int, row) -> dict:
    total = query.order_by(None).count()
    items = query.offset((page - 1) * size).limit(size).all()
    return {"total": total, "page": page, "size": size, "items": [row(i) for i in items]}


def _like(text: str) -> str:
    return f"%{text.strip()}%"


def _client_row(c: Clients) -> dict:
    return {
        "client_code": c.ClientCode,
        "name": " ".join(p for p in (c.FirstName, c.OtherNames, c.LastName) if p) or None,
        "phone_number": c.PhoneNumber,
        "ghana_card": c.NationalIDNumber,
        "date_of_birth": _iso(c.DateOfBirth),
        "agent_id": c.AgentID,
        "status": c.Status,
        "created_at": _iso(c.CreatedAt),
    }


def _policy_row(p: Policies) -> dict:
    return {
        "policy_number": p.PolicyNumber,
        "client_code": p.ClientCode,
        "product_name": p.Name,
        "premium": _num(p.Premium),
        "sum_assured": _num(p.SumAssured),
        "term": p.Term,
        "start_date": _iso(p.StartDate),
        "status": p.Status,
        "agent_id": p.AgentID,
        "created_at": _iso(p.CreatedAt),
    }


def _payment_row(r) -> dict:
    ph, policy_number = r
    return {
        "transaction_id": ph.transaction_id,
        "policy_number": policy_number,
        "amount": _num(ph.amount),
        "currency": ph.currency,
        "method": ph.payment_method,
        "status": ph.status,
        "created_at": _iso(ph.created_at),
    }


def _credit_row(pc: PaymentCredit) -> dict:
    return {
        "transaction_id": pc.transaction_id,
        "policy_number": pc.policy_number,
        "amount": _num(pc.amount),
        "phone_number": pc.phone_number,
        "trans_date": pc.trans_date,
        "status": pc.status,
        "note": pc.note,
        "created_at": _iso(pc.created_at),
    }


def _dependant_row(r) -> dict:
    d, policy_number = r
    return {
        "id": d.id,
        "client_code": d.ClientID,
        "relation_type": d.relation_type,
        "full_name": d.full_name,
        "date_of_birth": d.date_of_birth,
        "phone_number": d.phone_number,
        "allocation_percentage": _num(d.allocation_percentage),
        "policy_number": policy_number,
    }


def _family_row(r) -> dict:
    fm, policy_number, client_code = r
    return {
        "member_number": fm.member_number,
        "policy_number": policy_number,
        "client_code": client_code,
        "relation": fm.relation,
        "full_name": fm.full_name,
        "date_of_birth": _iso(fm.date_of_birth),
        "ghana_card": fm.ghana_card,
        "phone_number": fm.phone_number,
        "status": fm.status,
        "added_at": _iso(fm.created_at),
        "removed_at": _iso(fm.removed_at),
    }


def _method_row(m: PolicyPaymentMethod) -> dict:
    details = (f"{m.bank_name}, {m.account_name}, {m.account_number}" + (f" ({m.bank_branch})" if m.bank_branch else "")
               if m.payment_mode == "bank" else
               f"Staff ID {m.staff_id}, {m.employer}" + (f", {m.management_unit}" if m.management_unit else ""))
    return {
        "policy_number": m.policy_number, "client_code": m.client_code, "client_name": m.client_name,
        "phone_number": m.phone_number, "product_name": m.product_name, "premium": _num(m.premium),
        "frequency": m.frequency, "payment_mode": m.payment_mode, "details": details, "status": m.status,
        "set_at": _iso(m.created_at), "replaced_at": _iso(m.replaced_at),
    }


@router.get("/summary")
async def summary(db: Session = Depends(get_db)):
    by_status = dict(db.query(Policies.Status, func.count()).group_by(Policies.Status).all())
    active_premium = db.query(func.coalesce(func.sum(Policies.Premium), 0)).filter(Policies.Status == "Active").scalar()
    paid = db.query(func.count(), func.coalesce(func.sum(PaymentHistory.amount), 0)).filter(
        PaymentHistory.status.in_(PAID_STATUSES)).one()
    return {
        "clients": db.query(func.count(Clients.ClientID)).scalar(),
        "policies": sum(by_status.values()),
        "policies_by_status": by_status,
        "active_monthly_premium": _num(active_premium),
        "payments": paid[0],
        "payments_total": _num(paid[1]),
        "rejected_credits": db.query(func.count(PaymentCredit.id)).filter(PaymentCredit.status == "rejected").scalar(),
    }


@router.get("/clients")
async def list_clients(q: Optional[str] = None, page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=200),
                       db: Session = Depends(get_db)):
    """Search by phone, name, client code or Ghana Card. Newest first."""
    query = db.query(Clients)
    if q:
        like = _like(q)
        query = query.filter(or_(
            Clients.PhoneNumber.like(like), Clients.ClientCode.like(like), Clients.NationalIDNumber.like(like),
            Clients.FirstName.like(like), Clients.LastName.like(like), Clients.OtherNames.like(like),
        ))
    return _page(query.order_by(Clients.ClientID.desc()), page, size, _client_row)


@router.get("/clients/{client_code}")
async def client_detail(client_code: str, db: Session = Depends(get_db)):
    """One client with everything linked to them."""
    client = db.query(Clients).filter(Clients.ClientCode == client_code).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    policies = db.query(Policies).filter(Policies.ClientCode == client_code).order_by(Policies.PolicyID.desc()).all()
    ids = [p.PolicyID for p in policies]
    payments = db.query(PaymentHistory, Policies.PolicyNumber).join(
        Policies, Policies.PolicyID == PaymentHistory.policy_id,
    ).filter(PaymentHistory.policy_id.in_(ids)).order_by(PaymentHistory.id.desc()).all() if ids else []
    dependants = db.query(PoliciesDependant, Policies.PolicyNumber).outerjoin(
        Policies, Policies.PolicyID == PoliciesDependant.policy_id,
    ).filter(PoliciesDependant.ClientID == client_code).order_by(PoliciesDependant.id).all()
    plans = {fp.policy_id: fp for fp in db.query(PolicyFamilyPlan).filter(PolicyFamilyPlan.policy_id.in_(ids))} if ids else {}
    family = db.query(PolicyFamilyMember, Policies.PolicyNumber, Policies.ClientCode).join(
        Policies, Policies.PolicyID == PolicyFamilyMember.policy_id,
    ).filter(PolicyFamilyMember.policy_id.in_(ids)).order_by(
        PolicyFamilyMember.policy_id.desc(), PolicyFamilyMember.sequence).all() if ids else []
    active = {}
    for fm, _, _ in family:
        if fm.status == "Active":
            active[fm.policy_id] = active.get(fm.policy_id, 0) + 1
    numbers = [p.PolicyNumber for p in policies]
    credits = db.query(PaymentCredit).filter(PaymentCredit.policy_number.in_(numbers)).order_by(
        PaymentCredit.id.desc()).all() if numbers else []
    return {
        "client": {**_client_row(client), "gender": client.Gender, "id_type": client.IDType},
        "policies": [{**_policy_row(p), **({
            "family_plan": f"{plans[p.PolicyID].plan_type} {plans[p.PolicyID].tier_name}",
            "family_slots": plans[p.PolicyID].family_slots,
            "family_slots_used": active.get(p.PolicyID, 0),
        } if p.PolicyID in plans else {})} for p in policies],
        "family_members": [_family_row(r) for r in family],
        "payment_methods": [_method_row(r) for r in db.query(PolicyPaymentMethod).filter(
            PolicyPaymentMethod.policy_id.in_(ids)).order_by(PolicyPaymentMethod.id.desc())] if ids else [],
        "payments": [_payment_row(r) for r in payments],
        "payment_credits": [_credit_row(c) for c in credits],
        "dependants": [_dependant_row(r) for r in dependants],
    }


@router.get("/policies")
async def list_policies(q: Optional[str] = None, status: Optional[str] = None, page: int = Query(1, ge=1),
                        size: int = Query(25, ge=1, le=200), db: Session = Depends(get_db)):
    """Search by policy number, client code or product. Filter by status. Newest first."""
    query = db.query(Policies)
    if q:
        like = _like(q)
        query = query.filter(or_(Policies.PolicyNumber.like(like), Policies.ClientCode.like(like), Policies.Name.like(like)))
    if status:
        query = query.filter(Policies.Status == status)
    return _page(query.order_by(Policies.PolicyID.desc()), page, size, _policy_row)


@router.get("/payments")
async def list_payments(q: Optional[str] = None, page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=200),
                        db: Session = Depends(get_db)):
    """Payment history. Search by transaction id or policy number. Newest first."""
    query = db.query(PaymentHistory, Policies.PolicyNumber).outerjoin(Policies, Policies.PolicyID == PaymentHistory.policy_id)
    if q:
        like = _like(q)
        query = query.filter(or_(PaymentHistory.transaction_id.like(like), Policies.PolicyNumber.like(like)))
    return _page(query.order_by(PaymentHistory.id.desc()), page, size, _payment_row)


@router.get("/payment-credits")
async def list_payment_credits(q: Optional[str] = None, status: Optional[str] = None, page: int = Query(1, ge=1),
                               size: int = Query(25, ge=1, le=200), db: Session = Depends(get_db)):
    """IT Consortium payment notifications, including rejected ones still to follow up."""
    query = db.query(PaymentCredit)
    if q:
        like = _like(q)
        query = query.filter(or_(PaymentCredit.transaction_id.like(like), PaymentCredit.policy_number.like(like),
                                 PaymentCredit.phone_number.like(like)))
    if status:
        query = query.filter(PaymentCredit.status == status)
    return _page(query.order_by(PaymentCredit.id.desc()), page, size, _credit_row)


@router.get("/dependants")
async def list_dependants(q: Optional[str] = None, relation_type: Optional[str] = None, page: int = Query(1, ge=1),
                          size: int = Query(25, ge=1, le=200), db: Session = Depends(get_db)):
    """Dependants and beneficiaries. Search by name, phone or parent client code."""
    query = db.query(PoliciesDependant, Policies.PolicyNumber).outerjoin(
        Policies, Policies.PolicyID == PoliciesDependant.policy_id)
    if q:
        like = _like(q)
        query = query.filter(or_(PoliciesDependant.full_name.like(like), PoliciesDependant.phone_number.like(like),
                                 PoliciesDependant.ClientID.like(like)))
    if relation_type:
        query = query.filter(PoliciesDependant.relation_type == relation_type)
    return _page(query.order_by(PoliciesDependant.id.desc()), page, size, _dependant_row)


@router.get("/family-members")
async def list_family_members(q: Optional[str] = None, status: Optional[str] = None, page: int = Query(1, ge=1),
                              size: int = Query(25, ge=1, le=200), db: Session = Depends(get_db)):
    """Family-plan members (Ebusua). Search by name, member number, policy number, Ghana Card,
    phone or holder's client code. Filter by status (Active, Removed). Newest first."""
    query = db.query(PolicyFamilyMember, Policies.PolicyNumber, Policies.ClientCode).join(
        Policies, Policies.PolicyID == PolicyFamilyMember.policy_id)
    if q:
        like = _like(q)
        query = query.filter(or_(
            PolicyFamilyMember.full_name.like(like), PolicyFamilyMember.member_number.like(like),
            Policies.PolicyNumber.like(like), PolicyFamilyMember.ghana_card.like(like),
            PolicyFamilyMember.phone_number.like(like), Policies.ClientCode.like(like),
        ))
    if status:
        query = query.filter(PolicyFamilyMember.status == status)
    return _page(query.order_by(PolicyFamilyMember.id.desc()), page, size, _family_row)


@router.get("/payment-methods")
async def list_payment_methods(q: Optional[str] = None, payment_mode: Optional[str] = None, status: Optional[str] = None,
                               page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=200),
                               db: Session = Depends(get_db)):
    """Bank and Controller payment methods. Search by policy number, client code, name, phone,
    account number, staff ID or employer. Filter by mode and status (Active, Replaced). Newest first."""
    query = db.query(PolicyPaymentMethod)
    if q:
        like = _like(q)
        query = query.filter(or_(
            PolicyPaymentMethod.policy_number.like(like), PolicyPaymentMethod.client_code.like(like),
            PolicyPaymentMethod.client_name.like(like), PolicyPaymentMethod.phone_number.like(like),
            PolicyPaymentMethod.account_number.like(like), PolicyPaymentMethod.staff_id.like(like),
            PolicyPaymentMethod.employer.like(like), PolicyPaymentMethod.bank_name.like(like),
        ))
    if payment_mode:
        query = query.filter(PolicyPaymentMethod.payment_mode == payment_mode)
    if status:
        query = query.filter(PolicyPaymentMethod.status == status)
    return _page(query.order_by(PolicyPaymentMethod.id.desc()), page, size, _method_row)


@router.post("/payment-method", response_model=PaymentMethodResponse)
async def change_payment_method(payload: AdminPaymentMethodRequest, db: Session = Depends(get_db)):
    """Change a policy's payment method from the admin page. Same rules as the USSD endpoint:
    the new method becomes Active and the previous one is kept as Replaced."""
    policy = db.query(Policies).filter(Policies.PolicyNumber == payload.policy_number).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    holder = db.query(Clients).filter(Clients.ClientCode == policy.ClientCode).first()
    if not holder:
        raise HTTPException(status_code=404, detail="The policy's client record is missing")
    return save_payment_method(db, holder, policy, payload)
