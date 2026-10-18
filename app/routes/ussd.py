from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Optional, List, Literal
from datetime import datetime
import secrets

from app.setup.database import get_db
from app.models.migration import (
    Clients, Policies, Agents, PoliciesDependant, PaymentHistory, PolicyBenefits,
)
from app.schemas.ussd_schemas import *
from app.config.addition import get_dynamic_policy_config, calculate_premium_dynamic
from app.service.balance import PERIOD_MONTHS, policy_balance, ussd_line

router = APIRouter(prefix="/ussd")

# Live product catalog, refreshed from the external Sales App API on every
# catalog-touching request (not lazily/on-demand like the old USSD flow --
# every endpoint below that reads POLICY_CONFIG refreshes it itself first).
POLICY_CONFIG = {}


# ============= Shared helpers =============

def split_full_name(full_name: Optional[str]) -> tuple:
    """Split a Telco-supplied name into (first, last, other). Middle names go to other.
    Returns empty strings when no name was supplied, since FirstName/LastName are NOT NULL."""
    parts = (full_name or "").split()
    if not parts:
        return "", "", None
    if len(parts) == 1:
        return parts[0], "", None
    return parts[0], parts[-1], " ".join(parts[1:-1]) or None


def parse_dob(dob: str):
    return datetime.strptime(dob, "%d%m%Y").date()


def generate_policy_number(db: Session, dob) -> str:
    """POL + current year (YY) + client's DoB as YYMM + 2 random digits, e.g. POL26900437
    (issued 2026, client born April 1990). DoB is required at registration, and purchase
    captures it for older clients who have none, so it's always present here.

    Two digits allow only 100 numbers per (year, birth month), so a free suffix is picked from
    the ones not yet used; once all 100 are taken it widens to 3 digits, then 4. A widened number
    is longer than any 2-digit one, so it can't clash with another prefix's numbers."""
    prefix = f"POL{datetime.now().strftime('%y')}{dob.strftime('%y%m')}"
    taken = {
        n for (n,) in db.query(Policies.PolicyNumber).filter(Policies.PolicyNumber.like(f"{prefix}%"))
    }
    width = 2
    while True:
        free = [s for s in (f"{i:0{width}d}" for i in range(10 ** width)) if prefix + s not in taken]
        if free:
            return prefix + secrets.choice(free)
        width += 1


async def validate_agent_code(agent_code: str, db: Session) -> dict:
    """Validate agent code"""
    if agent_code == "EHI_0000_C":
        return {
            "is_valid": True,
            "agent_id": None,
            "agent_name": "Self Service",
            "message": "Agent validated successfully",
        }

    agent = db.query(Agents).filter(
        Agents.agent_code == agent_code,
        Agents.Status == 'Active',
    ).first()

    if not agent:
        return {"is_valid": False, "message": "Invalid or inactive agent code"}

    return {
        "is_valid": True,
        "agent_id": agent.AgentID,
        "agent_name": f"{agent.OtherNames}",
        "message": "Agent validated successfully",
    }


def resolve_client(db: Session, phone_number: Optional[str] = None, member_number: Optional[str] = None):
    """Resolve a client by member number (ClientCode) first, falling back to phone_number."""
    if member_number:
        client = db.query(Clients).filter(Clients.ClientCode == member_number).first()
        if client:
            return client
    if phone_number:
        return db.query(Clients).filter(Clients.PhoneNumber == phone_number).first()
    return None


async def refresh_catalog():
    global POLICY_CONFIG
    dynamic_cfg = await get_dynamic_policy_config()
    if dynamic_cfg:
        POLICY_CONFIG.update(dynamic_cfg)


def new_client(phone_number: str, full_name: Optional[str], dob: str, ghana_card: str, agent_id) -> Clients:
    """Build (not save) a client record. KYC: name comes from the Telco (via IT Consortium),
    DOB is entered by the customer. Gender isn't collected on USSD, so it stays 'Other'."""
    first_name, last_name, other_names = split_full_name(full_name)
    return Clients(
        ClientCode=f"CLI{phone_number}{datetime.now().strftime('%H%M%S')}",
        AgentID=agent_id,
        PhoneNumber=phone_number,
        FirstName=first_name,
        LastName=last_name,
        OtherNames=other_names,
        DateOfBirth=parse_dob(dob),
        NationalIDNumber=ghana_card,
        IDType="National ID",
        Gender='Other',
        Status='Active',
        CreatedAt=datetime.now(),
    )


def check_plan_choice(config: dict, plan_type: str, tier_value: Optional[str]) -> None:
    """422 unless plan_type is one of the product's plans and tier_value one of that plan's tiers."""
    p_struct = next((ps for ps in config.get("premium_structures", []) if ps["premium_type"] == plan_type), None)
    if not p_struct:
        raise HTTPException(status_code=422, detail="plan_type not found for this product")
    tiers = p_struct.get("tiers", [])
    if tiers and not tier_value:
        raise HTTPException(status_code=422, detail="tier_value is required for this plan")
    if tier_value and not any(str(t["tier_value"]) == str(tier_value) for t in tiers):
        raise HTTPException(status_code=422, detail="tier_value not found for this plan")


def add_policy(db: Session, client: Clients, config: dict, product_name: str, plan_type: str,
               tier_value: Optional[str], frequency: str, agent_id) -> Policies:
    """Price the choice and add a Pending policy plus its benefits to the session. The caller
    commits, so a new client and its policy can be saved together. No payment is started here:
    the policy becomes Active once a payment is credited to it."""
    calc = calculate_premium_dynamic(
        product_config=config, plan_type=plan_type, tier_value=tier_value,
        frequency=frequency, dob=client.DateOfBirth.strftime("%d%m%Y"),
    )
    premium = calc["total"]
    frequency = calc.get("frequency", frequency)  # a yearly price is always paid annually
    # No sum assured in the catalog: use a year of premiums at this frequency.
    sum_assured = calc["sum_assured"] or (premium * (12 // PERIOD_MONTHS.get(frequency, 1)))

    # Write anything already pending (e.g. a new client) first, so its errors aren't mistaken
    # below for a policy-number clash.
    db.flush()
    # Retry if a concurrent purchase grabbed the same number between picking and saving. The
    # savepoint undoes only this insert, never the rest of the caller's transaction.
    for attempt in range(5):
        policy = Policies(
            PolicyNumber=generate_policy_number(db, client.DateOfBirth),
            ClientCode=client.ClientCode,
            AgentID=agent_id,
            ProductID=1,
            SumAssured=sum_assured,
            Premium=premium,
            Term=12,
            PaymentFrequency=frequency,
            StartDate=datetime.now().date(),
            Status='Pending',
            Name=product_name,
        )
        try:
            with db.begin_nested():
                db.add(policy)
            break
        except IntegrityError:
            if attempt == 4:
                raise

    for benefit_text in config.get("benefits", []):
        db.add(PolicyBenefits(PolicyID=policy.PolicyID, ClientCode=client.ClientCode, BenefitText=benefit_text))
    return policy


# Sold only through the /ebusua endpoints, which record its family slots and members. Matched by
# name: the Sales App's is_family_plan flag is also set on ABS and Daakye, which onboard sells.
EBUSUA_PRODUCT = "Ebusua Health"


def is_ebusua(product_name: Optional[str]) -> bool:
    return product_name == EBUSUA_PRODUCT


def reject_family_plan(config: dict) -> None:
    """Ebusua needs its family slots and members recorded, which only the /ebusua endpoints do."""
    if is_ebusua(config.get("name")):
        raise HTTPException(
            status_code=422,
            detail=(f"{config.get('name', 'This product')} is a family plan: use POST /api/ussd/ebusua/register "
                    "for a new customer, or POST /api/ussd/ebusua/purchase for one already registered"),
        )


def find_or_build_client(db: Session, payload, agent_id):
    """(client, created) for a sign-up. A phone already registered with the same Ghana Card is
    reused, so a retried USSD session doesn't fail; any other phone/card clash is a 409. A new
    client is built but not added to the session -- the caller adds it with the policy."""
    by_phone = db.query(Clients).filter(Clients.PhoneNumber == payload.phone_number).first()
    by_card = db.query(Clients).filter(Clients.NationalIDNumber == payload.ghana_card).first()
    if by_phone and by_phone.NationalIDNumber == payload.ghana_card:
        # A reused client registered before DoB was mandatory gets the one entered now.
        if not by_phone.DateOfBirth:
            by_phone.DateOfBirth = parse_dob(payload.dob)
        return by_phone, False
    if by_phone:
        raise HTTPException(status_code=409, detail="This phone number is registered with a different Ghana Card number")
    if by_card:
        raise HTTPException(status_code=409, detail="This Ghana Card number is registered with a different phone number")
    return new_client(payload.phone_number, payload.full_name, payload.dob, payload.ghana_card, agent_id), True


# ============= Product catalog =============

@router.get("/products", response_model=List[ProductCatalogEntry])
async def list_products():
    """Full live product catalog -- build your own menu/selection UI from this."""
    await refresh_catalog()
    return [
        ProductCatalogEntry(
            name=name,
            product_code=cfg.get("productCode"),
            benefits=cfg.get("benefits", []),
            waiting_periods=cfg.get("waiting_periods", {}),
            premium_structures=cfg.get("premium_structures", []),
        )
        for name, cfg in POLICY_CONFIG.items()
    ]


@router.get("/products/{product_name}/benefits", response_model=PolicyBenefitsResponse)
async def get_product_benefits(product_name: str):
    await refresh_catalog()
    config = POLICY_CONFIG.get(product_name)
    if not config:
        raise HTTPException(status_code=404, detail="Product not found")
    return PolicyBenefitsResponse(
        product_name=product_name,
        benefits=config.get("benefits", []),
        waiting_periods=config.get("waiting_periods", {}),
    )


@router.get("/products/{product_name}/pricing", response_model=PolicyPricingResponse)
async def get_product_pricing(
    product_name: str,
    plan: Optional[str] = None,
    tier: Optional[str] = None,
    frequency: Optional[str] = None,
    dob: Optional[str] = None,
):
    await refresh_catalog()
    config = POLICY_CONFIG.get(product_name)
    if not config:
        raise HTTPException(status_code=404, detail="Product not found")

    calc = calculate_premium_dynamic(
        config,
        plan_type=plan or product_name,
        tier_value=tier,
        frequency=frequency or "monthly",
        dob=dob,
    )
    return PolicyPricingResponse(product_name=product_name, pricing=calc)


# ============= Customer registration =============

@router.post("/customers/register", response_model=CustomerRegisterResponse)
async def register_customer(payload: CustomerRegisterRequest, db: Session = Depends(get_db)):
    """Self or agent-assisted registration. Does not purchase a policy -- see /policies/purchase.
    KYC: name comes from the Telco (via IT Consortium), DOB is entered by the customer.
    Gender isn't collected on USSD, so it stays 'Other'."""
    if db.query(Clients).filter(Clients.PhoneNumber == payload.phone_number).first():
        raise HTTPException(status_code=409, detail="A client is already registered with this phone number")
    if db.query(Clients).filter(Clients.NationalIDNumber == payload.ghana_card).first():
        raise HTTPException(status_code=409, detail="A client is already registered with this Ghana Card number")

    agent_code = payload.agent_code if payload.registration_type == "agent_assisted" else "EHI_0000_C"
    agent_result = await validate_agent_code(agent_code, db)
    if not agent_result["is_valid"]:
        raise HTTPException(status_code=400, detail=agent_result["message"])

    try:
        client = new_client(
            payload.phone_number, payload.full_name, payload.dob, payload.ghana_card, agent_result["agent_id"],
        )
        db.add(client)
        db.commit()

        return CustomerRegisterResponse(
            status="success", message="Registration successful",
            client_code=client.ClientCode, phone_number=payload.phone_number,
            agent_id=agent_result["agent_id"],
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")


@router.post("/customers/register-dependent", response_model=CustomerRegisterResponse)
async def register_dependent(payload: DependentRegisterRequest, db: Session = Depends(get_db)):
    """Register a dependent under a parent/payer.
    under_18: stored as a dependant of the parent's record and policy -- no Ghana Card or
    phone needed, which also avoids duplicate-card errors when a parent insures several children.
    above_18: gets their own client record, with their own phone and Ghana Card, and is also
    linked to the parent's record and policy like a minor."""
    parent = resolve_client(db, phone_number=payload.parent_phone, member_number=payload.parent_member_number)
    if not parent:
        raise HTTPException(status_code=404, detail="Parent/payer not found -- register the parent first")

    agent_code = payload.agent_code if payload.registration_type == "agent_assisted" else "EHI_0000_C"
    agent_result = await validate_agent_code(agent_code, db)
    if not agent_result["is_valid"]:
        raise HTTPException(status_code=400, detail=agent_result["message"])

    policy_query = db.query(Policies).filter(Policies.ClientCode == parent.ClientCode)
    if payload.policy_number:
        policy = policy_query.filter(Policies.PolicyNumber == payload.policy_number).first()
        if not policy:
            raise HTTPException(status_code=404, detail="Policy not found for this parent")
    else:
        policy = policy_query.order_by(Policies.PolicyID.desc()).first()

    if payload.dependent_age_group == "under_18":
        try:
            db.add(PoliciesDependant(
                ClientID=parent.ClientCode,
                agent=agent_code,
                full_name=payload.dependent_full_name,
                date_of_birth=payload.dependent_dob,
                relation_type='Dependent',
                phone_number=payload.dependent_phone,
                policy_id=policy.PolicyID if policy else None,
            ))
            db.commit()
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")

        return CustomerRegisterResponse(
            status="success", message="Minor dependent registered under parent",
            client_code=parent.ClientCode, phone_number=parent.PhoneNumber,
            agent_id=agent_result["agent_id"],
        )

    if db.query(Clients).filter(Clients.PhoneNumber == payload.dependent_phone).first():
        raise HTTPException(status_code=409, detail="A client is already registered with this phone number")
    if db.query(Clients).filter(Clients.NationalIDNumber == payload.dependent_ghana_card).first():
        raise HTTPException(status_code=409, detail="A client is already registered with this Ghana Card number")

    try:
        client = new_client(
            payload.dependent_phone, payload.dependent_full_name, payload.dependent_dob,
            payload.dependent_ghana_card, agent_result["agent_id"],
        )
        db.add(client)
        # Link the adult to the parent too, so they show in the parent's /dependants list.
        db.add(PoliciesDependant(
            ClientID=parent.ClientCode,
            agent=agent_code,
            full_name=payload.dependent_full_name,
            date_of_birth=payload.dependent_dob,
            relation_type='Dependent',
            phone_number=payload.dependent_phone,
            policy_id=policy.PolicyID if policy else None,
        ))
        db.commit()

        return CustomerRegisterResponse(
            status="success", message="Dependent registration successful",
            client_code=client.ClientCode, phone_number=payload.dependent_phone,
            agent_id=agent_result["agent_id"],
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")


# ============= Policy purchase =============

@router.post("/policies/purchase", response_model=PolicyPurchaseResponse)
async def purchase_policy(payload: PolicyPurchaseRequest, db: Session = Depends(get_db)):
    """
    One-call replacement for the old product -> plan -> tier -> frequency ->
    confirm USSD turn sequence. The caller is expected to have already
    walked the user through those choices using GET /products and
    GET /products/{name}/pricing.
    """
    await refresh_catalog()

    client = resolve_client(db, phone_number=payload.phone_number, member_number=payload.member_number)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    config = POLICY_CONFIG.get(payload.product_name)
    if not config:
        raise HTTPException(status_code=404, detail="Product not found")
    reject_family_plan(config)

    check_plan_choice(config, payload.plan_type, payload.tier_value)

    # Clients registered before DoB became mandatory have none on file; capture it here,
    # since the policy number and age loading both need it.
    if not client.DateOfBirth:
        if not payload.dob:
            raise HTTPException(status_code=422, detail="dob is required: this client has no date of birth on file")
        client.DateOfBirth = parse_dob(payload.dob)

    # An agent facilitating this specific purchase can be attributed here even if
    # the client's own record has no agent (or a different one) attached.
    agent_id = client.AgentID
    if payload.agent_code:
        agent_result = await validate_agent_code(payload.agent_code, db)
        if not agent_result["is_valid"]:
            raise HTTPException(status_code=400, detail=agent_result["message"])
        if agent_result["agent_id"] is not None:
            agent_id = agent_result["agent_id"]

    try:
        policy = add_policy(
            db, client, config, payload.product_name, payload.plan_type,
            payload.tier_value, payload.frequency, agent_id,
        )
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Purchase failed: {str(e)}")

    # The policy stays Pending until a payment is credited via POST /payments/credit
    # (or a mandate / one-time payment set up with ref_no=policy_number).
    return PolicyPurchaseResponse(
        status="success", message="Policy created. It becomes active once payment is received.",
        client_code=client.ClientCode, policy_number=policy.PolicyNumber,
        premium=float(policy.Premium), sum_assured=float(policy.SumAssured),
        product_name=payload.product_name, term=policy.Term, frequency=policy.PaymentFrequency,
    )


# ============= Onboarding (register + purchase in one call) =============

@router.post("/customers/onboard", response_model=OnboardResponse)
async def onboard_customer(payload: OnboardRequest, db: Session = Depends(get_db)):
    """Register a customer and create their Pending policy in one transaction: both are
    saved or neither is. Everything that can fail is checked before anything is written.
    A phone already registered with the same Ghana Card is reused (client_created=false),
    so a retried USSD session doesn't fail. No payment is started."""
    agent_code = payload.agent_code if payload.registration_type == "agent_assisted" else "EHI_0000_C"
    agent_result = await validate_agent_code(agent_code, db)
    if not agent_result["is_valid"]:
        raise HTTPException(status_code=400, detail=agent_result["message"])

    await refresh_catalog()
    config = POLICY_CONFIG.get(payload.product_name)
    if not config:
        raise HTTPException(status_code=404, detail="Product not found")
    reject_family_plan(config)
    check_plan_choice(config, payload.plan_type, payload.tier_value)

    client, client_created = find_or_build_client(db, payload, agent_result["agent_id"])
    # Self sign-ups keep the client's own agent; an assisting agent gets this sale.
    agent_id = agent_result["agent_id"] if agent_result["agent_id"] is not None else client.AgentID

    try:
        if client_created:
            db.add(client)
        policy = add_policy(
            db, client, config, payload.product_name, payload.plan_type,
            payload.tier_value, payload.frequency, agent_id,
        )
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Onboarding failed: {str(e)}")

    return OnboardResponse(
        status="success",
        message=("Customer registered and policy created." if client_created else "Policy created for existing customer.")
                + " It becomes active once payment is received.",
        client_created=client_created,
        client_code=client.ClientCode,
        policy_number=policy.PolicyNumber,
        policy_status=policy.Status,
        product_name=payload.product_name,
        premium=float(policy.Premium),
        sum_assured=float(policy.SumAssured),
        term=policy.Term,
        frequency=policy.PaymentFrequency,
    )


# ============= Payments / balance =============

@router.post("/payments/voluntary", response_model=VoluntaryPaymentResponse)
async def voluntary_payment(payload: VoluntaryPaymentRequest, db: Session = Depends(get_db)):
    client = resolve_client(db, phone_number=payload.phone_number, member_number=payload.member_number)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    query = db.query(Policies).filter(Policies.ClientCode == client.ClientCode)
    policy = (
        query.filter(Policies.PolicyNumber == payload.policy_number).first()
        if payload.policy_number else query.first()
    )
    if not policy:
        raise HTTPException(status_code=404, detail="No policy found for this client")

    try:
        transaction_id = f"VOL{datetime.now().strftime('%Y%m%d%H%M%S')}{policy.PolicyID}"
        db.add(PaymentHistory(
            policy_id=policy.PolicyID,
            amount=payload.amount,
            currency='GHS',
            payment_method='Voluntary Payment',
            transaction_id=transaction_id,
            status='completed',
            description=f"Voluntary payment for policy {policy.PolicyNumber}",
        ))
        db.commit()
        return VoluntaryPaymentResponse(
            status="success", message="Payment processed successfully",
            transaction_id=transaction_id, policy_number=policy.PolicyNumber, amount=payload.amount,
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Payment failed: {str(e)}")


@router.post("/balance", response_model=BalanceResponse)
async def check_balance(payload: BalanceRequest, db: Session = Depends(get_db)):
    client = db.query(Clients).filter(Clients.PhoneNumber == payload.phone_number).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Pending policies are included so the customer sees what's needed to activate them;
    # Cancelled/Expired/Lapsed ones owe nothing more.
    policies = db.query(Policies).filter(
        Policies.ClientCode == client.ClientCode, Policies.Status.in_(['Active', 'Pending']),
    ).order_by(Policies.PolicyID.desc()).all()
    policies.sort(key=lambda p: p.Status != 'Active')  # Active first, newest first within each

    payments = {}
    if policies:
        rows = db.query(PaymentHistory).filter(
            PaymentHistory.policy_id.in_([p.PolicyID for p in policies]),
            PaymentHistory.status.in_(["Success", "completed"]),
        ).order_by(PaymentHistory.created_at, PaymentHistory.id).all()
        for r in rows:
            payments.setdefault(r.policy_id, []).append({
                "date": r.created_at.date() if r.created_at else None, "amount": float(r.amount),
                "method": r.payment_method, "transaction_id": r.transaction_id,
            })

    today = datetime.now().date()
    summaries = []
    for p in policies:
        b = policy_balance(float(p.Premium), p.PaymentFrequency, p.StartDate, p.Term, payments.get(p.PolicyID, []), today)
        if p.Status == 'Pending' and b["total_paid"] == 0:
            payment_status = "Awaiting first payment"
        elif b["arrears"] > 0:
            payment_status = "In arrears"  # an earlier period was left unpaid
        elif b["balance_due_now"] > 0:
            payment_status = "Payment due"  # only the current period is outstanding
        else:
            payment_status = "Up to date"
        summaries.append(PolicySummary(
            policy_number=p.PolicyNumber, premium=float(p.Premium), status=p.Status,
            product_name=p.Name, payment_status=payment_status, start_date=p.StartDate,
            ussd_text=ussd_line(p.PolicyNumber, p.Status, b), **b,
        ))

    active = [p for p in policies if p.Status == 'Active']
    return BalanceResponse(
        status="success",
        active_policies=len(active),
        total_premium=sum(float(p.Premium) for p in active),
        pending_policies=len(policies) - len(active),
        total_paid=round(sum(s.total_paid for s in summaries), 2),
        total_arrears=round(sum(s.arrears for s in summaries), 2),
        total_due_now=round(sum(s.balance_due_now for s in summaries), 2),
        policies=summaries,
    )


# ============= Policy cancellation =============

@router.post("/policies/cancel", response_model=CancelPolicyResponse)
async def cancel_policy(payload: CancelPolicyRequest, db: Session = Depends(get_db)):
    client = db.query(Clients).filter(Clients.PhoneNumber == payload.phone_number).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    query = db.query(Policies).filter(Policies.ClientCode == client.ClientCode, Policies.Status == 'Active')
    if payload.policy_number:
        query = query.filter(Policies.PolicyNumber == payload.policy_number)
    policies = query.all()
    if not policies:
        raise HTTPException(status_code=404, detail="No active policy found to cancel")

    cancelled = []
    for p in policies:
        p.Status = 'Cancelled'
        cancelled.append(p.PolicyNumber)
    db.commit()

    # Cancellation is final: a cancelled policy is never reactivated, and a new application
    # is a brand-new registration. (Stopping a payment mandate is separate and doesn't cancel.)
    return CancelPolicyResponse(
        status="success",
        message="Policy cancelled. Coverage has ended and cannot be reactivated; to be covered again, apply for a new policy.",
        cancelled_policy_numbers=cancelled,
    )


# ============= Beneficiaries =============

@router.post("/beneficiaries", response_model=BeneficiaryResponse)
async def add_beneficiary(payload: AddBeneficiaryRequest, db: Session = Depends(get_db)):
    client = db.query(Clients).filter(Clients.PhoneNumber == payload.phone_number).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    if payload.policy_number:
        policy = db.query(Policies).filter(
            Policies.ClientCode == client.ClientCode, Policies.PolicyNumber == payload.policy_number,
        ).first()
        if not policy:
            raise HTTPException(status_code=404, detail="Policy not found for this client")
    else:
        policy = db.query(Policies).filter(
            Policies.ClientCode == client.ClientCode,
        ).order_by(Policies.PolicyID.desc()).first()

    existing_count = db.query(PoliciesDependant).filter(
        PoliciesDependant.ClientID == client.ClientCode,
        PoliciesDependant.relation_type == 'Beneficiary',
    ).count()
    if existing_count >= 6:
        raise HTTPException(status_code=409, detail="Maximum number of beneficiaries (6) already reached")

    try:
        db.add(PoliciesDependant(
            ClientID=client.ClientCode,
            full_name=payload.full_name,
            date_of_birth=payload.date_of_birth,
            relation_type='Beneficiary',
            phone_number=payload.beneficiary_phone,
            allocation_percentage=payload.allocation_percentage,
            policy_id=policy.PolicyID if policy else None,
        ))
        db.commit()
        return BeneficiaryResponse(
            status="success", message="Beneficiary added successfully",
            full_name=payload.full_name, date_of_birth=payload.date_of_birth,
            beneficiary_phone=payload.beneficiary_phone, allocation_percentage=payload.allocation_percentage,
            policy_number=policy.PolicyNumber if policy else None,
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Request failed: {str(e)}")


@router.get("/beneficiaries", response_model=BeneficiaryListResponse)
async def list_beneficiaries(phone_number: str, db: Session = Depends(get_db)):
    """List beneficiaries/dependents for a client, enriched with their linked policy's
    premium/status -- also satisfies the mockup's 'My Dependent's Balance' screen."""
    client = db.query(Clients).filter(Clients.PhoneNumber == phone_number).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    dependants = db.query(PoliciesDependant).filter(
        PoliciesDependant.ClientID == client.ClientCode,
        PoliciesDependant.relation_type.in_(['Beneficiary', 'Dependent']),
    ).all()

    entries = []
    for d in dependants:
        policy = db.query(Policies).filter(Policies.PolicyID == d.policy_id).first() if d.policy_id else None
        entries.append(BeneficiaryEntry(
            relation_type=d.relation_type,
            full_name=d.full_name,
            date_of_birth=d.date_of_birth,
            beneficiary_phone=d.phone_number,
            allocation_percentage=d.allocation_percentage,
            policy_number=policy.PolicyNumber if policy else None,
            policy_premium=float(policy.Premium) if policy else None,
            policy_status=policy.Status if policy else None,
        ))

    return BeneficiaryListResponse(status="success", count=len(entries), beneficiaries=entries)


# ============= Lookups: client, policies, dependants (separate reads) =============

def require_client(db: Session, phone_number: Optional[str], member_number: Optional[str]) -> Clients:
    if not phone_number and not member_number:
        raise HTTPException(status_code=422, detail="one of phone_number or member_number is required")
    client = resolve_client(db, phone_number=phone_number, member_number=member_number)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


@router.get("/clients", response_model=ClientDetailsResponse)
async def get_client(
    phone_number: Optional[str] = None,
    member_number: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Client KYC details only -- policies and dependants have their own endpoints."""
    client = require_client(db, phone_number, member_number)
    return ClientDetailsResponse(client=ClientDetails(
        client_code=client.ClientCode,
        first_name=client.FirstName or None,
        last_name=client.LastName or None,
        other_names=client.OtherNames,
        phone_number=client.PhoneNumber,
        date_of_birth=client.DateOfBirth,
        ghana_card=client.NationalIDNumber,
        gender=client.Gender,
        agent_id=client.AgentID,
        status=client.Status,
        created_at=client.CreatedAt,
    ))


@router.get("/policies", response_model=PolicyListResponse)
async def get_policies(
    phone_number: Optional[str] = None,
    member_number: Optional[str] = None,
    policy_number: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """A client's policies, newest first, with what has been paid on each.
    Filter to one policy with policy_number, or by status (Active, Pending, Cancelled, ...)."""
    client = require_client(db, phone_number, member_number)

    query = db.query(Policies).filter(Policies.ClientCode == client.ClientCode)
    if policy_number:
        query = query.filter(Policies.PolicyNumber == policy_number)
    if status:
        query = query.filter(Policies.Status == status)
    policies = query.order_by(Policies.PolicyID.desc()).all()
    if policy_number and not policies:
        raise HTTPException(status_code=404, detail="Policy not found for this client")

    totals = {}
    if policies:
        rows = db.query(
            PaymentHistory.policy_id, func.sum(PaymentHistory.amount), func.max(PaymentHistory.created_at),
        ).filter(
            PaymentHistory.policy_id.in_([p.PolicyID for p in policies]),
            PaymentHistory.status.in_(["Success", "completed"]),
        ).group_by(PaymentHistory.policy_id).all()
        totals = {policy_id: (float(total or 0), last) for policy_id, total, last in rows}

    return PolicyListResponse(
        client_code=client.ClientCode,
        count=len(policies),
        policies=[
            PolicyDetails(
                policy_number=p.PolicyNumber,
                product_name=p.Name,
                premium=float(p.Premium),
                sum_assured=float(p.SumAssured),
                term=p.Term,
                start_date=p.StartDate,
                end_date=p.EndDate,
                status=p.Status,
                agent_id=p.AgentID,
                total_paid=totals.get(p.PolicyID, (0, None))[0],
                last_payment_date=totals.get(p.PolicyID, (0, None))[1],
                created_at=p.CreatedAt,
            )
            for p in policies
        ],
    )


@router.get("/dependants", response_model=DependantListResponse)
async def get_dependants(
    phone_number: Optional[str] = None,
    member_number: Optional[str] = None,
    policy_number: Optional[str] = None,
    relation_type: Optional[Literal["Dependent", "Beneficiary"]] = None,
    db: Session = Depends(get_db),
):
    """A client's dependants (minors registered under them) and beneficiaries.
    Filter by policy_number or relation_type."""
    client = require_client(db, phone_number, member_number)

    query = db.query(PoliciesDependant, Policies.PolicyNumber).outerjoin(
        Policies, Policies.PolicyID == PoliciesDependant.policy_id,
    ).filter(PoliciesDependant.ClientID == client.ClientCode)
    if policy_number:
        query = query.filter(Policies.PolicyNumber == policy_number)
    if relation_type:
        query = query.filter(PoliciesDependant.relation_type == relation_type)
    rows = query.order_by(PoliciesDependant.id).all()

    return DependantListResponse(
        client_code=client.ClientCode,
        count=len(rows),
        dependants=[
            DependantDetails(
                id=d.id,
                relation_type=d.relation_type,
                full_name=d.full_name,
                date_of_birth=d.date_of_birth,
                phone_number=d.phone_number,
                allocation_percentage=float(d.allocation_percentage) if d.allocation_percentage is not None else None,
                policy_number=pol_number,
            )
            for d, pol_number in rows
        ],
    )


# ============= Support / Terms (static content) =============

@router.get("/support", response_model=SupportInfoResponse)
async def contact_support():
    return SupportInfoResponse(
        phone="0800-EQUITY (0800-378489)",
        email="support@equityhealthinsurance.com",
        hours="Mon-Fri, 8:00am-5:00pm GMT",
        message="Welcome to Equity Health Insurance Customer Support",
    )


@router.get("/terms", response_model=TermsInfoResponse)
async def terms_and_conditions():
    return TermsInfoResponse(
        summary="By registering for or purchasing an Equity Health Insurance policy via USSD, "
                "you agree to the plan's benefits, waiting periods, and premium terms as presented "
                "at the point of purchase, and to Equity Health Insurance's full Terms and Conditions.",
        url="https://equityhealthinsurance.com/terms",
    )


# ============= Health / lookups =============

@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "USSD API"}


@router.get("/lookup/member/{member_number}")
async def lookup_member_by_number(member_number: str, db: Session = Depends(get_db)):
    client = db.query(Clients).filter(Clients.ClientCode == member_number).first()
    if not client:
        return {"status": "error", "message": "Member not found"}

    policies = db.query(Policies).filter(Policies.ClientCode == client.ClientCode).all()
    return {
        "status": "success",
        "client": {
            "client_code": client.ClientCode, "first_name": client.FirstName, "last_name": client.LastName,
            "other_names": client.OtherNames, "phone_number": client.PhoneNumber,
            "date_of_birth": client.DateOfBirth.isoformat() if client.DateOfBirth else None,
            "ghana_card": client.NationalIDNumber, "status": client.Status,
        },
        "policies": [
            {"policy_number": p.PolicyNumber, "policy_name": p.Name, "premium": float(p.Premium), "status": p.Status}
            for p in policies
        ],
    }


@router.get("/lookup/phone/{phone_number}")
async def lookup_by_phone(phone_number: str, db: Session = Depends(get_db)):
    client = db.query(Clients).filter(Clients.PhoneNumber == phone_number).first()
    if not client:
        return {"status": "error", "message": "Member not found"}

    policies = db.query(Policies).filter(Policies.ClientCode == client.ClientCode).all()
    return {
        "status": "success",
        "client": {
            "client_code": client.ClientCode, "first_name": client.FirstName, "last_name": client.LastName,
            "other_names": client.OtherNames, "phone_number": client.PhoneNumber,
            "date_of_birth": client.DateOfBirth.isoformat() if client.DateOfBirth else None,
            "ghana_card": client.NationalIDNumber, "status": client.Status,
        },
        "policies": [
            {"policy_number": p.PolicyNumber, "policy_name": p.Name, "premium": float(p.Premium), "status": p.Status}
            for p in policies
        ],
    }
