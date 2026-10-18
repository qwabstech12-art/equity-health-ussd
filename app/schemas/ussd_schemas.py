from pydantic import BaseModel, Field, validator, field_validator, model_validator
from typing import Optional, List, Dict, Any, Literal, Union
from datetime import datetime, date
import datetime as dt
import re


# ============= Product Catalog =============

class Tier(BaseModel):
    tier_value: str
    tier_name: str
    premium_amount: float
    sum_assured: Optional[float] = None


class PremiumStructure(BaseModel):
    premium_type: str
    base_premium: float = 0
    policy_fee: float = 0
    tiers: List[Tier] = []


class ProductCatalogEntry(BaseModel):
    name: str
    product_code: Optional[str] = None
    benefits: List[str] = []
    waiting_periods: Dict[str, str] = {}
    premium_structures: List[PremiumStructure] = []


class PolicyBenefitsResponse(BaseModel):
    status: str = "success"
    product_name: str
    benefits: List[str]
    waiting_periods: Dict[str, str] = {}


class PolicyPricingResponse(BaseModel):
    status: str = "success"
    product_name: str
    pricing: Dict[str, Any]
    currency: str = "GHS"


# ============= Customer Registration =============

GHANA_CARD_PATTERN = re.compile(r"^GHA-\d{9}-\d$")


def normalize_ghana_card(value: Optional[str]) -> Optional[str]:
    """Uppercase and strip spaces, then check the GHA-XXXXXXXXX-X format.
    Only the format is checked -- authenticity needs the NIA API, which isn't available yet."""
    if value is None or not value.strip():
        return None
    card = re.sub(r"\s+", "", value).upper()
    if not GHANA_CARD_PATTERN.match(card):
        raise ValueError(f"{ghana_card_problem(card)}. It should be GHA-, 9 digits, a dash and 1 digit, e.g. GHA-123456789-1")
    return card


def ghana_card_problem(card: str) -> str:
    """Say what's wrong with a card number that failed GHANA_CARD_PATTERN."""
    if not card.startswith("GHA-"):
        return "Ghana Card number must start with GHA-"
    parts = card[4:].split("-")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return "Ghana Card number must be digits separated by one dash after GHA-"
    middle, last = parts
    if len(middle) != 9:
        return f"Ghana Card number has {len(middle)} digits between GHA- and the last dash; it needs 9"
    return f"Ghana Card number has {len(last)} digits after the last dash; it needs 1"


def validate_dob(value: str) -> str:
    """DDMMYYYY, not in the future and not older than 120 years."""
    try:
        dob = datetime.strptime(value, "%d%m%Y").date()
    except (ValueError, TypeError):
        raise ValueError("date of birth must be in DDMMYYYY format")
    today = date.today()
    if dob > today:
        raise ValueError("date of birth cannot be in the future")
    if today.year - dob.year > 120:
        raise ValueError("date of birth is not valid")
    return value


def validate_phone(value: Optional[str]) -> str:
    """Spaces removed; 9 to 15 digits with an optional leading +."""
    phone = re.sub(r"\s+", "", value or "")
    if not re.fullmatch(r"\+?\d{9,15}", phone):
        raise ValueError("phone_number must be 9 to 15 digits, e.g. 233244123456")
    return phone


def age_on(dob: str, today: Optional[date] = None) -> int:
    """Age in whole years from a DDMMYYYY date of birth."""
    born = datetime.strptime(dob, "%d%m%Y").date()
    today = today or date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


class CustomerRegisterRequest(BaseModel):
    phone_number: str
    ghana_card: str
    full_name: Optional[str] = None  # supplied by IT Consortium from the Telco; may be missing
    dob: str  # DDMMYYYY, entered by the customer on the USSD screen
    registration_type: Literal["self", "agent_assisted"] = "self"
    agent_code: Optional[str] = None

    @validator("ghana_card")
    def ghana_card_format(cls, v):
        card = normalize_ghana_card(v)
        if not card:
            raise ValueError("ghana_card is required")
        return card

    @validator("dob")
    def dob_format(cls, v):
        return validate_dob(v)

    @validator("agent_code", always=True)
    def agent_code_required_if_assisted(cls, v, values):
        if values.get("registration_type") == "agent_assisted" and not v:
            raise ValueError("agent_code is required when registration_type is agent_assisted")
        return v


class DependentRegisterRequest(BaseModel):
    """A minor (under_18) is linked to the parent/payer's record and needs no Ghana Card or
    phone of their own. An adult dependent gets their own client record and needs both."""
    parent_phone: Optional[str] = None
    parent_member_number: Optional[str] = None
    policy_number: Optional[str] = None  # parent's policy to attach the minor to; defaults to their latest
    dependent_full_name: Optional[str] = None
    dependent_age_group: Literal["under_18", "above_18"]
    dependent_dob: str  # DDMMYYYY
    dependent_ghana_card: Optional[str] = None  # required if above_18
    dependent_phone: Optional[str] = None  # required if above_18
    registration_type: Literal["self", "agent_assisted"] = "self"
    agent_code: Optional[str] = None

    @validator("parent_member_number", always=True)
    def parent_identifier_required(cls, v, values):
        if not v and not values.get("parent_phone"):
            raise ValueError("one of parent_phone or parent_member_number is required")
        return v

    @validator("dependent_dob")
    def dob_format(cls, v):
        return validate_dob(v)

    @validator("dependent_ghana_card", always=True)
    def card_required_if_above_18(cls, v, values):
        card = normalize_ghana_card(v)
        if values.get("dependent_age_group") == "above_18" and not card:
            raise ValueError("dependent_ghana_card is required when dependent_age_group is above_18")
        return card

    @validator("dependent_phone", always=True)
    def phone_required_if_above_18(cls, v, values):
        if values.get("dependent_age_group") == "above_18" and not v:
            raise ValueError("dependent_phone is required when dependent_age_group is above_18")
        return v

    @validator("agent_code", always=True)
    def agent_code_required_if_assisted(cls, v, values):
        if values.get("registration_type") == "agent_assisted" and not v:
            raise ValueError("agent_code is required when registration_type is agent_assisted")
        return v


class CustomerRegisterResponse(BaseModel):
    status: str
    message: str
    client_code: Optional[str] = None
    phone_number: Optional[str] = None
    agent_id: Optional[int] = None


# ============= Policy Purchase =============

class PolicyPurchaseRequest(BaseModel):
    phone_number: Optional[str] = None
    member_number: Optional[str] = None
    product_name: str
    plan_type: str
    tier_value: Optional[str] = None
    frequency: Literal["monthly", "quarterly", "half-yearly", "annually"] = "monthly"
    dob: Optional[str] = None  # DDMMYYYY; required only if the client has no DoB on file (it's then saved)
    agent_code: Optional[str] = None  # facilitating agent for this specific transaction

    @validator("dob")
    def dob_format(cls, v):
        return validate_dob(v) if v else v

    @validator("member_number")
    def identifier_required(cls, v, values):
        if not v and not values.get("phone_number"):
            raise ValueError("one of phone_number or member_number is required")
        return v


class PolicyPurchaseResponse(BaseModel):
    status: str
    message: str
    client_code: Optional[str] = None
    policy_number: Optional[str] = None
    premium: Optional[float] = None
    sum_assured: Optional[float] = None
    product_name: Optional[str] = None
    term: Optional[int] = None
    frequency: Optional[str] = None  # as saved; a yearly-priced tier is always "annually"


# ============= Onboarding (register + purchase in one call) =============

class OnboardRequest(CustomerRegisterRequest):
    """Registration fields (with their validators) plus the policy choice."""
    product_name: str
    plan_type: str
    tier_value: Optional[str] = None
    frequency: Literal["monthly", "quarterly", "half-yearly", "annually"] = "monthly"

    @validator("phone_number")
    def phone_format(cls, v):
        return validate_phone(v)


class OnboardResponse(BaseModel):
    status: str
    message: str
    client_created: bool
    client_code: str
    policy_number: str
    policy_status: str
    product_name: str
    premium: float
    sum_assured: float
    term: int
    frequency: str  # as saved; a yearly-priced tier is always "annually"


# ============= Family plans (Ebusua Health) =============

class EbusuaRegisterRequest(CustomerRegisterRequest):
    """The policy holder plus the plan and how many family members to cover. The number of
    family members sets the tier (0 = M, 3 = M+3) and so the yearly premium; the members
    themselves are added later with POST /ebusua/members."""
    plan_type: str
    family_members: int = Field(..., ge=0, description="Family members to cover besides the policy holder (0 = M, 3 = M+3)")

    @validator("phone_number")
    def phone_format(cls, v):
        return validate_phone(v)


class EbusuaRegisterResponse(BaseModel):
    status: str
    message: str
    client_created: bool
    client_code: str
    policy_number: str
    policy_status: str
    plan_type: str
    tier: str  # e.g. M+3
    premium: float
    frequency: str
    family_slots: int
    family_slots_filled: int = 0


class EbusuaPurchaseRequest(BaseModel):
    """Ebusua for a customer who is already registered: found by phone or member number."""
    phone_number: Optional[str] = None
    member_number: Optional[str] = None  # client code
    plan_type: str
    family_members: int = Field(..., ge=0, description="Family members to cover besides the policy holder (0 = M, 3 = M+3)")
    dob: Optional[str] = None  # DDMMYYYY; only if the client has no date of birth on file
    agent_code: Optional[str] = None  # facilitating agent for this sale

    @validator("dob")
    def dob_format(cls, v):
        return validate_dob(v) if v else v

    @model_validator(mode="after")
    def identifier_given(self):
        if not self.phone_number and not self.member_number:
            raise ValueError("one of phone_number or member_number is required")
        return self


class EbusuaTier(BaseModel):
    tier_value: str
    tier_name: str  # M, M+1 ... M+5
    family_members: int  # covered besides the policy holder
    premium: float  # per year


class EbusuaPlan(BaseModel):
    plan_type: str  # SHEA, OAK, MAHOGANY, ROSEWOOD
    tiers: List[EbusuaTier]


class EbusuaProductResponse(BaseModel):
    status: str = "success"
    product_name: str
    product_code: Optional[str] = None
    benefits: List[str] = []
    waiting_periods: Dict[str, str] = {}
    frequency: str  # always annually
    max_family_members: int  # besides the policy holder
    plans: List[EbusuaPlan]


class FamilyMemberIn(BaseModel):
    relation: Literal["spouse", "child", "parent", "other"]
    full_name: str
    dob: str  # DDMMYYYY
    ghana_card: Optional[str] = None  # required for adults (18+), optional for children
    phone_number: Optional[str] = None

    @validator("full_name")
    def name_given(cls, v):
        if not v or not v.strip():
            raise ValueError("full_name is required")
        return " ".join(v.split())

    @validator("dob")
    def dob_format(cls, v):
        return validate_dob(v)

    @validator("ghana_card", always=True)
    def card_for_adults(cls, v, values):
        card = normalize_ghana_card(v)
        if not card and values.get("dob") and age_on(values["dob"]) >= 18:
            raise ValueError("ghana_card is required for family members aged 18 or over")
        return card

    @validator("phone_number")
    def phone_format(cls, v):
        return validate_phone(v) if v else None


class AddFamilyMembersRequest(BaseModel):
    phone_number: str  # the policy holder's; proves the policy is theirs
    policy_number: str
    members: List[FamilyMemberIn] = Field(..., min_length=1)


class FamilyMemberOut(BaseModel):
    member_number: str
    relation: str
    full_name: str
    date_of_birth: date
    ghana_card: Optional[str] = None
    phone_number: Optional[str] = None
    adult: bool


class FamilyPolicyOut(BaseModel):
    policy_number: str
    product_name: Optional[str] = None
    plan_type: str
    tier: str
    policy_status: str
    premium: float
    frequency: str
    family_slots: int
    slots_used: int
    slots_left: int
    members: List[FamilyMemberOut] = []


class AddFamilyMembersResponse(BaseModel):
    status: str
    message: str
    added: List[FamilyMemberOut]
    policy: FamilyPolicyOut


class FamilyPoliciesResponse(BaseModel):
    status: str = "success"
    client_code: str
    policies: List[FamilyPolicyOut] = []


class RemoveFamilyMemberResponse(BaseModel):
    status: str
    message: str
    removed_member_number: str
    policy: FamilyPolicyOut


# ============= Payments / Balance =============

class VoluntaryPaymentRequest(BaseModel):
    phone_number: Optional[str] = None
    member_number: Optional[str] = None
    policy_number: Optional[str] = None
    amount: float = Field(..., gt=0)


class VoluntaryPaymentResponse(BaseModel):
    status: str
    message: str
    transaction_id: Optional[str] = None
    policy_number: Optional[str] = None
    amount: Optional[float] = None


class BalanceRequest(BaseModel):
    phone_number: str


class BalancePeriod(BaseModel):
    period: int
    start: date
    end: date
    due: float
    paid: float
    balance: float
    status: Optional[str] = None  # Paid | Part paid | Unpaid | Upcoming


class BalancePayment(BaseModel):
    date: Optional[dt.date] = None  # dt.date: a field named `date` would shadow the type
    amount: float
    method: Optional[str] = None
    transaction_id: Optional[str] = None


class PolicySummary(BaseModel):
    # The first three fields are the original response; the rest were added after them.
    policy_number: str
    premium: float  # per payment, at the policy's frequency
    status: str
    product_name: Optional[str] = None
    payment_status: Optional[str] = None  # Awaiting first payment | Up to date | Payment due | In arrears
    frequency: Optional[str] = None
    start_date: Optional[date] = None
    term_ends: Optional[date] = None
    total_paid: float = 0
    total_due_to_date: float = 0
    arrears: float = 0  # unpaid from periods before the current one
    current_period: Optional[BalancePeriod] = None
    balance_due_now: float = 0  # arrears + what's left on the current period
    credit: float = 0  # paid beyond what's due so far; counts toward the next period
    next_due_date: Optional[date] = None
    next_due_amount: Optional[float] = None
    ussd_text: Optional[str] = None
    periods: List[BalancePeriod] = []
    payments: List[BalancePayment] = []


class BalanceResponse(BaseModel):
    status: str
    message: Optional[str] = None
    active_policies: int = 0
    total_premium: float = 0  # sum of premiums on Active policies, as before
    pending_policies: int = 0
    total_paid: float = 0
    total_arrears: float = 0
    total_due_now: float = 0
    policies: List[PolicySummary] = []


# ============= Policy Cancellation =============

class CancelPolicyRequest(BaseModel):
    phone_number: str
    policy_number: Optional[str] = None  # if omitted, cancels every Active policy for the client


class CancelPolicyResponse(BaseModel):
    status: str
    message: str
    cancelled_policy_numbers: List[str] = []


# ============= Beneficiaries =============

class AddBeneficiaryRequest(BaseModel):
    phone_number: str
    full_name: str
    date_of_birth: str
    beneficiary_phone: str
    allocation_percentage: float = Field(..., gt=0, le=100)
    policy_number: Optional[str] = None  # if omitted, attaches to the client's most recent policy


class BeneficiaryResponse(BaseModel):
    status: str
    message: str
    full_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    beneficiary_phone: Optional[str] = None
    allocation_percentage: Optional[float] = None
    policy_number: Optional[str] = None


class BeneficiaryEntry(BaseModel):
    relation_type: Optional[str] = None  # "Beneficiary" | "Dependent" (minor linked to the parent)
    full_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    beneficiary_phone: Optional[str] = None
    allocation_percentage: Optional[float] = None
    policy_number: Optional[str] = None
    policy_premium: Optional[float] = None
    policy_status: Optional[str] = None


class BeneficiaryListResponse(BaseModel):
    status: str
    message: Optional[str] = None
    count: int = 0
    max_allowed: int = 6
    beneficiaries: List[BeneficiaryEntry] = []


# ============= Lookups (client / policies / dependants) =============

class ClientDetails(BaseModel):
    client_code: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    other_names: Optional[str] = None
    phone_number: str
    date_of_birth: Optional[date] = None
    ghana_card: Optional[str] = None
    gender: Optional[str] = None
    agent_id: Optional[int] = None
    status: Optional[str] = None
    created_at: Optional[datetime] = None


class ClientDetailsResponse(BaseModel):
    status: str = "success"
    client: ClientDetails


class PolicyDetails(BaseModel):
    policy_number: str
    product_name: Optional[str] = None
    premium: float
    sum_assured: float
    term: int
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: str
    agent_id: Optional[int] = None
    total_paid: float = 0
    last_payment_date: Optional[datetime] = None
    created_at: Optional[datetime] = None


class PolicyListResponse(BaseModel):
    status: str = "success"
    client_code: str
    count: int = 0
    policies: List[PolicyDetails] = []


class DependantDetails(BaseModel):
    id: int
    relation_type: Optional[str] = None  # "Dependent" (minor under the parent) | "Beneficiary"
    full_name: Optional[str] = None
    date_of_birth: Optional[str] = None  # DDMMYYYY, as captured on USSD
    phone_number: Optional[str] = None
    allocation_percentage: Optional[float] = None
    policy_number: Optional[str] = None


class DependantListResponse(BaseModel):
    status: str = "success"
    client_code: str
    count: int = 0
    dependants: List[DependantDetails] = []


# ============= Mandate =============

class MandateCreateRequest(BaseModel):
    client_phone: str
    amount_to_debit: str
    frequency_type: str = "MONTHLY"
    frequency: str = "1"
    start_date: str
    end_date: str
    debit_day: str
    ref_no: str


class MandateResponse(BaseModel):
    status: str
    message: str
    mandate_id: Optional[str] = None
    response_code: Optional[str] = None
    response_message: Optional[str] = None


class MandateDetailsResponse(BaseModel):
    status: str = "success"
    message: str
    found: bool = False
    data: Optional[Any] = None


# ============= One-time payment (Uniwallet) =============

class OneTimePaymentRequest(BaseModel):
    msisdn: str
    amount: str
    network: str
    currency: str = "GHS"
    ref_no: str


class OneTimePaymentResponse(BaseModel):
    status: str
    ref_no: str
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class OneTimeStatusResponse(BaseModel):
    status: str  # "success" | "pending" | "failed" | "not_found"
    message: str
    policy_activated: bool = False
    data: Optional[Dict[str, Any]] = None


# ============= Payment gateway webhook payloads (Transflow / Uniwallet -> us) =============

class MandateCallbackCreate(BaseModel):
    responseCode: str
    responseMessage: str
    merchantId: str
    productId: str
    mandateId: Optional[str] = None
    clientPhone: str
    thirdPartyReferenceNo: str


class UniwalletCallbackCreate(BaseModel):
    uniwalletTransactionId: Optional[str] = None
    networkTransactionId: Optional[str] = None
    refNo: Optional[str] = None
    productId: Optional[str] = None
    msisdn: Optional[str] = None
    amount: Optional[str] = None
    narration: Optional[str] = None
    timestamp: Optional[str] = None
    responseCode: Optional[str] = None
    responseMessage: Optional[str] = None
    network: Optional[str] = None
    transflowId: Optional[str] = None


class MandateTransactionCallbackCreate(BaseModel):
    responseCode: str
    responseMessage: str
    momTransactionId: Optional[str] = None
    debitOrderTransactionId: Optional[str] = None
    merchantId: str
    productId: str
    mandateId: Optional[str] = None
    clientPhone: str
    amount: Optional[str] = None
    thirdPartyReferenceNo: str


class PaymentCreditRequest(BaseModel):
    """Payment notification from IT Consortium -- credits a received payment to a policy."""
    transactionId: str
    policyNumber: str
    amount: Union[str, float]
    phoneNumber: str
    transDate: str

    @validator("transactionId", "policyNumber", "phoneNumber", "transDate")
    def not_blank(cls, v):
        if not str(v).strip():
            raise ValueError("must not be empty")
        return str(v).strip()

    @validator("amount")
    def amount_positive(cls, v):
        try:
            amount = float(v)
        except (TypeError, ValueError):
            raise ValueError("amount must be a number")
        if amount <= 0:
            raise ValueError("amount must be greater than 0")
        return amount


class PaymentCreditResponse(BaseModel):
    status: str  # "credited" | "rejected"
    message: str
    transactionId: str
    policyNumber: str
    amount: Optional[float] = None
    policyStatus: Optional[str] = None
    duplicate: bool = False


class CallbackAck(BaseModel):
    responseCode: str
    responseMessage: str


# ============= Support / Terms (static content) =============

class SupportInfoResponse(BaseModel):
    status: str = "success"
    phone: str
    email: str
    hours: str
    message: Optional[str] = None


class TermsInfoResponse(BaseModel):
    status: str = "success"
    summary: str
    url: Optional[str] = None


# ============= Agent Validation =============

class AgentValidationResponse(BaseModel):
    status: str
    message: str
    agent_id: Optional[int] = None
    agent_name: Optional[str] = None
    is_valid: bool = False


# ============= Payment method (bank / Controller) =============

def _required_text(v, name):
    if v is None or not str(v).strip():
        raise ValueError(f"{name} is required")
    return " ".join(str(v).split())


class BankDetails(BaseModel):
    bank_name: str
    branch: Optional[str] = None
    account_name: str
    account_number: str  # no format check: Ghanaian banks use different lengths and formats

    @field_validator("bank_name", "account_name", "account_number")
    @classmethod
    def given(cls, v, info):
        return _required_text(v, info.field_name)

    @validator("branch")
    def tidy(cls, v):
        return " ".join(v.split()) if v and v.strip() else None


class ControllerDetails(BaseModel):
    """Payment by deduction from a government salary through the Controller and
    Accountant-General's Department."""
    staff_id: str
    employer: str  # e.g. Ghana Education Service
    management_unit: Optional[str] = None

    @field_validator("staff_id", "employer")
    @classmethod
    def given(cls, v, info):
        return _required_text(v, info.field_name)

    @validator("management_unit")
    def tidy(cls, v):
        return " ".join(v.split()) if v and v.strip() else None


class PaymentMethodChoice(BaseModel):
    """The mode and its details, shared by the USSD and admin requests."""
    payment_mode: Literal["bank", "controller"]
    bank: Optional[BankDetails] = None
    controller: Optional[ControllerDetails] = None

    @model_validator(mode="after")
    def details_match_mode(self):
        if self.payment_mode == "bank":
            if not self.bank:
                raise ValueError("bank details are required when payment_mode is bank")
            if self.controller:
                raise ValueError("send controller details only when payment_mode is controller")
        else:
            if not self.controller:
                raise ValueError("controller details are required when payment_mode is controller")
            if self.bank:
                raise ValueError("send bank details only when payment_mode is bank")
        return self


class PaymentMethodRequest(PaymentMethodChoice):
    phone_number: str  # the policy holder's; proves the policy is theirs
    policy_number: str


class AdminPaymentMethodRequest(PaymentMethodChoice):
    """From the admin page: staff are signed in with the admin key, so no holder phone is needed."""
    policy_number: str


class PaymentMethodOut(BaseModel):
    payment_mode: str
    status: str
    client_code: str
    client_name: Optional[str] = None
    phone_number: str
    ghana_card: Optional[str] = None
    policy_number: str
    product_name: Optional[str] = None
    premium: Optional[float] = None
    frequency: Optional[str] = None
    bank: Optional[BankDetails] = None
    controller: Optional[ControllerDetails] = None
    set_at: Optional[datetime] = None
    replaced_at: Optional[datetime] = None


class PaymentMethodResponse(BaseModel):
    status: str
    message: str
    payment_method: PaymentMethodOut


class PaymentMethodHistoryResponse(BaseModel):
    status: str = "success"
    policy_number: str
    current: Optional[PaymentMethodOut] = None
    history: List[PaymentMethodOut] = []  # replaced methods, newest first
