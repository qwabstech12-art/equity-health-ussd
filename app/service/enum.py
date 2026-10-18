from enum import Enum

class AgeGroup(Enum):
    YOUNG = "0-59 years"
    MIDDLE_AGED = "60-75 years"
    SENIOR = "75+ years"

class PolicyType(Enum):
    MICRO_INSURANCE = "Micro Insurance"
    NHIS_TOP_UP = "NHIS Top Up"
    TELEMEDICINE = "Telemedicine"
    ABS = "Ayaresa Banbo Sika"
    EBUSUA = "Ebusua"

class UserType(Enum):
    EXISTING = "Existing Customer"
    NEW = "New Customer"
    DEPENDENT = "Buy For Dependent"

class RegistrationType(Enum):
    SELF = "Self Registration"
    AGENT_ASSISTED = "Agent Assisted Registration"

class AgentFlowType(Enum):
    NEW_CUSTOMER = "New Customer"
    EXISTING_CUSTOMER = "Existing Customer"
    BUY_FOR_DEPENDENT = "Buy For Dependent"

class BeneficiaryStep(Enum):
    ENTER_NAME = "enter_name"
    ENTER_DOB = "enter_dob"
    ENTER_PHONE = "enter_phone"
    ENTER_ALLOCATION = "enter_allocation"
    CONFIRM_DETAILS = "confirm_details"
    CONFIRM_ALLOCATION = "confirm_allocation"

class UpdateRecordsStep(Enum):
    MAIN = "main"
    UPDATE_POLICY_PLAN = "update_policy_plan"
    POLICY_PLAN_CONFIRM = "policy_plan_confirm"
    CANCEL_RECURRING = "cancel_recurring"
    ADD_BENEFICIARY = "add_beneficiary"