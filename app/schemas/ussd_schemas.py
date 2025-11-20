from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import date, datetime
from decimal import Decimal

class USSDResponse(BaseModel):
    message: str
    should_end: bool = False

class RegisterRequest(BaseModel):
    product_name: str
    ghana_card: str
    phonenumber: str
    agent_code: Optional[str] = "EHI_0000_C" 

class AgentRegisterRequest(BaseModel):
    product_name: str
    phonenumber: str
    ghana_card: str
    agent_code: str  

    @validator('agent_code')
    def validate_agent_code(cls, v):
        if not v or v.strip() == "":
            raise ValueError("Agent code is required for agent-assisted registration")
        return v

class CustomerRegistrationResponse(BaseModel):
    status: str
    message: str
    policy_number: Optional[str] = None
    premium: Optional[float] = None
    product_name: Optional[str] = None
    sum_assured: Optional[float] = None
    term: Optional[int] = None
    mandate_id: Optional[str] = None
    
    
    
class AgeGroupResponse(BaseModel):
    young_age: str
    middle_age: str
    senior_age: str

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

class BeneficiaryCreate(BaseModel):
    policy_number: str
    full_name: str
    date_of_birth: str
    phone_number: str
    percentage_allocation: float

class BeneficiaryUpdate(BaseModel):
    policy_number: str
    beneficiary_name: str
    new_name: Optional[str] = None
    new_phone: Optional[str] = None
    new_allocation: Optional[float] = None

class BeneficiaryResponse(BaseModel):
    name: str
    date_of_birth: str
    phone_number: str
    percentage_allocation: float

class PolicyTopupRequest(BaseModel):
    policy_number: str
    amount: float
    pin: str

class ReferralRequest(BaseModel):
    referrer_policy_number: str
    friend_phone_number: str

class DependentCreate(BaseModel):
    policy_number: str
    full_name: str
    date_of_birth: str
    relation_type: str

class WithdrawRewardsRequest(BaseModel):
    policy_number: str
    amount: float

class UpdatePolicyPlanRequest(BaseModel):
    policy_number: str
    new_plan: str

class CancelRecurringRequest(BaseModel):
    policy_number: str
    pin: str

class USSDHandlerRequest(BaseModel):
    session_id: str
    service_code: str
    phone_number: str
    text: str = ""

class InsuranceProductResponse(BaseModel):
    id: str
    product_code: str
    name: str
    premium: float
    sum_assured: float
    term: int
    status: str

class ReferralEarningsResponse(BaseModel):
    status: str
    policy_number: str
    policy_status: str
    premium: float
    earnings_summary: Dict[str, Any]
    breakdown: Dict[str, Any]

class BalanceResponse(BaseModel):
    status: str
    policy_number: str
    premium: float
    sum_assured: float
    status: str

class TermsResponse(BaseModel):
    status: str
    terms_url: str
    message: str

class ContactSupportResponse(BaseModel):
    status: str
    message: str
    support_contact: str

class ResetPINRequest(BaseModel):
    policy_number: str
    current_pin: str
    new_pin: str

class ForgotPINRequest(BaseModel):
    policy_number: str
    phone_number: str

class VoluntaryPaymentRequest(BaseModel):
    policy_number: str
    amount: float
    pin: str

class AgentValidationResponse(BaseModel):
    status: str
    message: str
    agent_id: Optional[int] = None
    agent_name: Optional[str] = None
    is_valid: bool = False