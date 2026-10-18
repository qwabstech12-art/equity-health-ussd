"""Ebusua Health family plan.

Session 1 (POST /register): the policy holder buys a plan for a chosen number of family
members; that number sets the tier (M, M+1 ... M+5) and so the yearly premium.
Session 2, any time later (POST /members): family members are added into the slots paid for.
Each gets a member number: the policy number plus a running number (POL26900412-1, -2, ...)."""
import re
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.setup.database import get_db
from app.models.migration import Clients, Policies, PolicyFamilyPlan, PolicyFamilyMember
from app.schemas.ussd_schemas import (
    EbusuaRegisterRequest, EbusuaRegisterResponse, EbusuaPurchaseRequest, EbusuaProductResponse, EbusuaPlan,
    EbusuaTier, AddFamilyMembersRequest, AddFamilyMembersResponse,
    FamilyMemberOut, FamilyPolicyOut, FamilyPoliciesResponse, RemoveFamilyMemberResponse,
)
from app.routes import ussd

router = APIRouter(prefix="/ussd/ebusua")

EBUSUA = ussd.EBUSUA_PRODUCT
CLOSED_STATUSES = ("Cancelled", "Expired", "Lapsed")


def _age(born: date, today: Optional[date] = None) -> int:
    today = today or date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


async def _ebusua_config() -> dict:
    await ussd.refresh_catalog()
    config = ussd.POLICY_CONFIG.get(EBUSUA)
    if not config:
        raise HTTPException(status_code=404, detail=f"{EBUSUA} is not in the product catalog")
    return config


def _max_members(config: dict) -> int:
    """Most family members besides the holder. Family members can be any age; there's no
    separate limit on adults (the catalog's max_adults is deliberately not applied)."""
    plan = config.get("product_plan") or {}
    return max(0, int(plan.get("max_family_members") or 6) - 1)


def _tier_for(p_struct: dict, family_members: int) -> Optional[dict]:
    """The tier named M (no family) or M+n. Falls back to tier_value n+1 if names change."""
    for tier in p_struct.get("tiers", []):
        m = re.fullmatch(r"\s*M\s*(?:\+\s*(\d+))?\s*", tier.get("tier_name") or "", re.IGNORECASE)
        if m and int(m.group(1) or 0) == family_members:
            return tier
    return next((t for t in p_struct.get("tiers", []) if str(t["tier_value"]) == str(family_members + 1)), None)


def _member_out(m: PolicyFamilyMember) -> FamilyMemberOut:
    return FamilyMemberOut(
        member_number=m.member_number, relation=m.relation, full_name=m.full_name,
        date_of_birth=m.date_of_birth, ghana_card=m.ghana_card, phone_number=m.phone_number,
        adult=_age(m.date_of_birth) >= 18,
    )


def _active_members(db: Session, policy: Policies) -> list:
    return db.query(PolicyFamilyMember).filter(
        PolicyFamilyMember.policy_id == policy.PolicyID, PolicyFamilyMember.status == "Active",
    ).order_by(PolicyFamilyMember.sequence).all()


def _policy_out(db: Session, policy: Policies, plan: PolicyFamilyPlan) -> FamilyPolicyOut:
    members = _active_members(db, policy)
    return FamilyPolicyOut(
        policy_number=policy.PolicyNumber, product_name=policy.Name, plan_type=plan.plan_type,
        tier=plan.tier_name, policy_status=policy.Status, premium=float(policy.Premium),
        frequency=policy.PaymentFrequency, family_slots=plan.family_slots, slots_used=len(members),
        slots_left=plan.family_slots - len(members), members=[_member_out(m) for m in members],
    )


def _holder_policy(db: Session, phone_number: str, policy_number: str):
    """(holder, policy, family plan), checking the policy belongs to this phone number."""
    holder = db.query(Clients).filter(Clients.PhoneNumber == phone_number).first()
    if not holder:
        raise HTTPException(status_code=404, detail="Client not found")
    policy = db.query(Policies).filter(
        Policies.PolicyNumber == policy_number, Policies.ClientCode == holder.ClientCode,
    ).first()
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found for this phone number")
    plan = db.query(PolicyFamilyPlan).filter(PolicyFamilyPlan.policy_id == policy.PolicyID).first()
    if not plan:
        raise HTTPException(status_code=422, detail="This policy is not a family plan")
    return holder, policy, plan


def _plan_and_tier(config: dict, plan_type: str, family_members: int) -> dict:
    """The tier for this plan and family size, or a 422 saying what's allowed."""
    plans = config.get("premium_structures", [])
    p_struct = next((ps for ps in plans if ps["premium_type"] == plan_type), None)
    if not p_struct:
        valid = ", ".join(ps["premium_type"] for ps in plans)
        raise HTTPException(status_code=422, detail=f"plan_type must be one of: {valid}")
    max_members = _max_members(config)
    if family_members > max_members:
        raise HTTPException(status_code=422, detail=f"{EBUSUA} covers at most {max_members} family members besides the policy holder")
    tier = _tier_for(p_struct, family_members)
    if not tier:
        raise HTTPException(status_code=422, detail=f"No {plan_type} tier for {family_members} family members")
    return tier


def _create_policy(db: Session, client: Clients, client_created: bool, config: dict, plan_type: str,
                   tier: dict, family_members: int, agent_id) -> EbusuaRegisterResponse:
    """Save the (new) client, the Pending yearly policy and its family slots in one transaction."""
    try:
        if client_created:
            db.add(client)
        policy = ussd.add_policy(
            db, client, config, EBUSUA, plan_type, str(tier["tier_value"]), "annually", agent_id,
        )
        db.add(PolicyFamilyPlan(
            policy_id=policy.PolicyID, plan_type=plan_type, tier_value=str(tier["tier_value"]),
            tier_name=tier["tier_name"], family_slots=family_members,
        ))
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Saving the policy failed: {str(e)}")

    return EbusuaRegisterResponse(
        status="success",
        message=(f"{EBUSUA} {plan_type} ({tier['tier_name']}) created. "
                 + (f"Add up to {family_members} family members at any time. " if family_members else "")
                 + "It becomes active once payment is received."),
        client_created=client_created, client_code=client.ClientCode, policy_number=policy.PolicyNumber,
        policy_status=policy.Status, plan_type=plan_type, tier=tier["tier_name"],
        premium=float(policy.Premium), frequency=policy.PaymentFrequency, family_slots=family_members,
    )


@router.get("/products", response_model=EbusuaProductResponse)
async def products():
    """Only the Ebusua catalog: each plan's tiers from M (holder only) to M+5, the yearly price
    and how many family members each covers. Build the Ebusua USSD menus from this."""
    config = await _ebusua_config()
    plans = []
    for ps in config.get("premium_structures", []):
        tiers = []
        for t in ps.get("tiers", []):
            m = re.fullmatch(r"\s*M\s*(?:\+\s*(\d+))?\s*", t.get("tier_name") or "", re.IGNORECASE)
            count = int(m.group(1) or 0) if m else int(t["tier_value"]) - 1
            tiers.append(EbusuaTier(tier_value=str(t["tier_value"]), tier_name=t["tier_name"], family_members=count,
                                    premium=float(t["premium_amount"] or 0)))
        plans.append(EbusuaPlan(plan_type=ps["premium_type"], tiers=sorted(tiers, key=lambda t: t.family_members)))
    return EbusuaProductResponse(
        product_name=EBUSUA, product_code=config.get("productCode"), benefits=config.get("benefits", []),
        waiting_periods=config.get("waiting_periods", {}), frequency="annually",
        max_family_members=_max_members(config), plans=plans,
    )


@router.post("/register", response_model=EbusuaRegisterResponse)
async def register(payload: EbusuaRegisterRequest, db: Session = Depends(get_db)):
    """Register a new policy holder and buy Ebusua for `family_members` people besides them.
    The policy is Pending and paid yearly; family members are added later with POST /members.
    For a customer who is already registered, use POST /purchase instead."""
    agent_code = payload.agent_code if payload.registration_type == "agent_assisted" else "EHI_0000_C"
    agent_result = await ussd.validate_agent_code(agent_code, db)
    if not agent_result["is_valid"]:
        raise HTTPException(status_code=400, detail=agent_result["message"])

    config = await _ebusua_config()
    tier = _plan_and_tier(config, payload.plan_type, payload.family_members)

    client, client_created = ussd.find_or_build_client(db, payload, agent_result["agent_id"])
    agent_id = agent_result["agent_id"] if agent_result["agent_id"] is not None else client.AgentID
    return _create_policy(db, client, client_created, config, payload.plan_type, tier, payload.family_members, agent_id)


@router.post("/purchase", response_model=EbusuaRegisterResponse)
async def purchase(payload: EbusuaPurchaseRequest, db: Session = Depends(get_db)):
    """Buy Ebusua for a customer who is already registered, found by phone or member number;
    no Ghana Card or other KYC is asked again. Same tiers, pricing and family slots as /register."""
    client = ussd.resolve_client(db, phone_number=payload.phone_number, member_number=payload.member_number)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found; register them with POST /api/ussd/ebusua/register")

    config = await _ebusua_config()
    tier = _plan_and_tier(config, payload.plan_type, payload.family_members)

    # Clients registered before DoB became mandatory have none on file; the policy number needs it.
    if not client.DateOfBirth:
        if not payload.dob:
            raise HTTPException(status_code=422, detail="dob is required: this client has no date of birth on file")
        client.DateOfBirth = ussd.parse_dob(payload.dob)

    agent_id = client.AgentID
    if payload.agent_code:
        agent_result = await ussd.validate_agent_code(payload.agent_code, db)
        if not agent_result["is_valid"]:
            raise HTTPException(status_code=400, detail=agent_result["message"])
        if agent_result["agent_id"] is not None:
            agent_id = agent_result["agent_id"]

    return _create_policy(db, client, False, config, payload.plan_type, tier, payload.family_members, agent_id)


@router.post("/members", response_model=AddFamilyMembersResponse)
async def add_members(payload: AddFamilyMembersRequest, db: Session = Depends(get_db)):
    """Add family members into the slots the policy was bought for. All are added or none."""
    holder, policy, plan = _holder_policy(db, payload.phone_number, payload.policy_number)
    if policy.Status in CLOSED_STATUSES:
        raise HTTPException(status_code=409, detail=f"This policy is {policy.Status}; family members can't be added")

    existing = _active_members(db, policy)
    slots_left = plan.family_slots - len(existing)
    if plan.family_slots == 0:
        raise HTTPException(status_code=409, detail=f"This policy ({plan.tier_name}) covers the policy holder only; it has no family slots")
    if slots_left <= 0:
        raise HTTPException(status_code=409, detail=f"All {plan.family_slots} family slots on this policy are used")
    if len(payload.members) > slots_left:
        raise HTTPException(status_code=409, detail=f"Only {slots_left} family slot{'s' if slots_left != 1 else ''} left on this policy; {len(payload.members)} members were sent")

    cards = [m.ghana_card for m in payload.members if m.ghana_card]
    taken = {holder.NationalIDNumber, *(m.ghana_card for m in existing)}
    if len(cards) != len(set(cards)) or taken.intersection(cards):
        raise HTTPException(status_code=409, detail="A Ghana Card number appears more than once on this policy")

    last = db.query(PolicyFamilyMember.sequence).filter(
        PolicyFamilyMember.policy_id == policy.PolicyID,
    ).order_by(PolicyFamilyMember.sequence.desc()).first()
    sequence = last[0] if last else 0  # removed members keep their numbers, so count from the highest ever

    added = []
    try:
        for m in payload.members:
            sequence += 1
            row = PolicyFamilyMember(
                policy_id=policy.PolicyID, sequence=sequence, member_number=f"{policy.PolicyNumber}-{sequence}",
                relation=m.relation, full_name=m.full_name, date_of_birth=datetime.strptime(m.dob, "%d%m%Y").date(),
                ghana_card=m.ghana_card, phone_number=m.phone_number, status="Active",
            )
            db.add(row)
            added.append(row)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This policy was updated at the same moment; please try again")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Adding family members failed: {str(e)}")

    out = _policy_out(db, policy, plan)
    return AddFamilyMembersResponse(
        status="success",
        message=f"{len(added)} added. {out.slots_used} of {out.family_slots} family slots used, {out.slots_left} left.",
        added=[_member_out(r) for r in added], policy=out,
    )


@router.get("/members", response_model=FamilyPoliciesResponse)
async def list_members(phone_number: str, policy_number: Optional[str] = None, db: Session = Depends(get_db)):
    """The holder's family-plan policies with their slots and members, newest first."""
    holder = db.query(Clients).filter(Clients.PhoneNumber == phone_number).first()
    if not holder:
        raise HTTPException(status_code=404, detail="Client not found")
    query = db.query(Policies, PolicyFamilyPlan).join(
        PolicyFamilyPlan, PolicyFamilyPlan.policy_id == Policies.PolicyID,
    ).filter(Policies.ClientCode == holder.ClientCode)
    if policy_number:
        query = query.filter(Policies.PolicyNumber == policy_number)
    rows = query.order_by(Policies.PolicyID.desc()).all()
    if policy_number and not rows:
        raise HTTPException(status_code=404, detail="Family-plan policy not found for this phone number")
    return FamilyPoliciesResponse(client_code=holder.ClientCode, policies=[_policy_out(db, p, plan) for p, plan in rows])


@router.delete("/members/{member_number}", response_model=RemoveFamilyMemberResponse)
async def remove_member(member_number: str, phone_number: str, db: Session = Depends(get_db)):
    """Remove a family member (e.g. entered wrongly). Their slot becomes free; their member
    number is kept on record and never given to anyone else."""
    member = db.query(PolicyFamilyMember).filter(
        PolicyFamilyMember.member_number == member_number, PolicyFamilyMember.status == "Active",
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Family member not found")
    policy = db.query(Policies).filter(Policies.PolicyID == member.policy_id).first()
    _, policy, plan = _holder_policy(db, phone_number, policy.PolicyNumber)

    member.status = "Removed"
    member.removed_at = datetime.now()
    db.commit()

    out = _policy_out(db, policy, plan)
    return RemoveFamilyMemberResponse(
        status="success",
        message=f"{member.full_name} removed. {out.slots_left} family slot{'s' if out.slots_left != 1 else ''} free.",
        removed_member_number=member_number, policy=out,
    )
