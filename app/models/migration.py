from sqlalchemy import (
    Column, Integer, String, Enum, DateTime, Date, Boolean, TIMESTAMP, ForeignKey, DECIMAL, Text, Index, JSON, CHAR, Float, Numeric
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from datetime import datetime
from app.setup.connection import Base


class SaleHierarchy(Base):
    __tablename__ = "SaleHierarchy"
    HierarchyID = Column(Integer, primary_key=True, autoincrement=True)
    HierarchyName = Column(String(50), unique=True, nullable=False)

class SalesTeams(Base):
    __tablename__ = "SalesTeams"
    TeamID = Column(Integer, primary_key=True, autoincrement=True)
    TeamName = Column(String(255), unique=True, nullable=False)
    TeamLeaderID = Column(Integer, nullable=True)
    CreatedAt = Column(TIMESTAMP, default=func.current_timestamp())
    UpdatedAt = Column(TIMESTAMP, default=func.current_timestamp(), onupdate=func.current_timestamp())

class Agents(Base):
    __tablename__ = "Agents"
    AgentID = Column(Integer, primary_key=True, autoincrement=True)
    SaleHierarchyID = Column(Integer, ForeignKey("SaleHierarchy.HierarchyID"), nullable=False)
    SalesTeamID = Column(Integer, ForeignKey("SalesTeams.TeamID"), nullable=True)
    OtherNames = Column(String(255))
    Gender = Column(Enum('Male', 'Female', 'Other'), nullable=False)
    MaritalStatus = Column(Enum('Single', 'Married', 'Divorced', 'Widowed', 'Other'), default='Single')
    DateOfBirth = Column(Date, nullable=False)
    Address = Column(String(255))
    MobileNo = Column(String(15), unique=True, nullable=False)
    MobileMoneyNo = Column(String(15), unique=True)
    Email = Column(String(255), unique=True)
    BenefitStartDate = Column(Date)
    AgentPicture = Column(String(255))
    Status = Column(Enum('Active', 'Inactive'), default='Active')
    agent_code = Column(String(255), unique=True)
    password = Column(String(255))
    IsDeleted = Column(Boolean, default=False)
    CreatedAt = Column(TIMESTAMP, default=func.current_timestamp())
    UpdatedAt = Column(TIMESTAMP, default=func.current_timestamp(), onupdate=func.current_timestamp())

    clients = relationship("Clients", back_populates="agent")
    policies = relationship("Policies", back_populates="agent", foreign_keys="[Policies.AgentID]")
    approved_policies = relationship("Policies", foreign_keys="[Policies.ApprovedBy]", back_populates="approver")
    commissions = relationship("Commissions", back_populates="agent")


class Branches(Base):
    __tablename__ = "Branches"  
    BranchID = Column(Integer, primary_key=True, autoincrement=True)
    BranchName = Column(String(255), unique=True, nullable=False)
    Location = Column(String(255), nullable=False)
    CreatedAt = Column(TIMESTAMP, default=func.current_timestamp())
    UpdatedAt = Column(TIMESTAMP, default=func.current_timestamp(), onupdate=func.current_timestamp())

    clients = relationship("Clients", back_populates="branch")
    commissions = relationship("Commissions", back_populates="branch")





class BankDetails(Base):
    __tablename__ = "BankDetails"
    BankID = Column(Integer, primary_key=True, autoincrement=True)
    BankName = Column(String(100), nullable=False)
    Branch = Column(String(100), nullable=False)
    AccountNumber = Column(String(50), unique=True, nullable=False)
    AgentID = Column(Integer, ForeignKey("Agents.AgentID"))
    CreatedAt = Column(TIMESTAMP, default=func.current_timestamp())
    UpdatedAt = Column(TIMESTAMP, default=func.current_timestamp(), onupdate=func.current_timestamp())


class AgentStatusHistory(Base):
    __tablename__ = "AgentStatusHistory"
    StatusID = Column(Integer, primary_key=True, autoincrement=True)
    AgentID = Column(Integer, ForeignKey("Agents.AgentID"))
    Status = Column(Enum('Active', 'Inactive'), nullable=False)
    ChangedAt = Column(TIMESTAMP, default=func.current_timestamp())
    ChangedBy = Column(Integer, ForeignKey("Users.UserID"), nullable=True)


class Benefits(Base):
    __tablename__ = "Benefits"
    BenefitID = Column(Integer, primary_key=True, autoincrement=True)
    AgentID = Column(Integer, ForeignKey("Agents.AgentID"))
    BenefitType = Column(String(255), nullable=False)
    Amount = Column(DECIMAL(10, 2), nullable=False)
    StartDate = Column(Date, nullable=False)
    EndDate = Column(Date)
    CreatedAt = Column(TIMESTAMP, default=func.current_timestamp())
    UpdatedAt = Column(TIMESTAMP, default=func.current_timestamp(), onupdate=func.current_timestamp())


class AgentPerformance(Base):
    __tablename__ = "AgentPerformance"
    PerformanceID = Column(Integer, primary_key=True, autoincrement=True)
    AgentID = Column(Integer, ForeignKey("Agents.AgentID"))
    TotalSales = Column(DECIMAL(10, 2), nullable=False)
    Target = Column(DECIMAL(10, 2), nullable=False)
    AchievementPercentage = Column(DECIMAL(5, 2), nullable=False)
    EvaluationDate = Column(Date, nullable=False)
    CreatedAt = Column(TIMESTAMP, default=func.current_timestamp())
    UpdatedAt = Column(TIMESTAMP, default=func.current_timestamp(), onupdate=func.current_timestamp())


class AgentTraining(Base):
    __tablename__ = "AgentTraining"
    TrainingID = Column(Integer, primary_key=True, autoincrement=True)
    AgentID = Column(Integer, ForeignKey("Agents.AgentID"))
    TrainingName = Column(String(255), nullable=False)
    CompletionDate = Column(Date, nullable=False)
    CertificateIssued = Column(Boolean, default=False)
    CreatedAt = Column(TIMESTAMP, default=func.current_timestamp())
    UpdatedAt = Column(TIMESTAMP, default=func.current_timestamp(), onupdate=func.current_timestamp())


class Commissions(Base):
    __tablename__ = "commissions"
    
    CommissionID = Column(Integer, primary_key=True, autoincrement=True)
    AgentID = Column(Integer, ForeignKey("Agents.AgentID"))
    BranchID = Column(Integer, ForeignKey("Branches.BranchID")) 
    PolicyID = Column(String(50))
    Amount = Column(DECIMAL(10, 2), nullable=False)
    CommissionDate = Column(Date, nullable=False)
    Status = Column(Enum('Pending', 'Paid', 'Cancelled', name='commission_status'), 
                  default='Pending')
    CreatedAt = Column(TIMESTAMP, default=func.current_timestamp())
    UpdatedAt = Column(TIMESTAMP, default=func.current_timestamp(), 
                      onupdate=func.current_timestamp())

    agent = relationship("Agents", back_populates="commissions")
    branch = relationship("Branches", back_populates="commissions")



class AgentCredentials(Base):
    __tablename__ = "AgentCredentials"
    CredentialID = Column(Integer, primary_key=True, autoincrement=True)
    AgentID = Column(Integer, ForeignKey("Agents.AgentID"), unique=True)
    Username = Column(String(50), unique=True, nullable=False)
    PasswordHash = Column(String(255), nullable=False)
    LastLogin = Column(TIMESTAMP)
    CreatedAt = Column(TIMESTAMP, default=func.current_timestamp())
    UpdatedAt = Column(TIMESTAMP, default=func.current_timestamp(), onupdate=func.current_timestamp())

class Roles(Base):
    __tablename__ = "Roles"
    RoleID = Column(Integer, primary_key=True, autoincrement=True)
    RoleName = Column(String(100), unique=True, nullable=False)
    Description = Column(Text)
    CreatedAt = Column(TIMESTAMP, default=func.current_timestamp())
    UpdatedAt = Column(TIMESTAMP, default=func.current_timestamp(), onupdate=func.current_timestamp())


class Permissions(Base):
    __tablename__ = "Permissions"
    PermissionID = Column(Integer, primary_key=True, autoincrement=True)
    PermissionName = Column(String(100), unique=True, nullable=False)
    Description = Column(Text)
    CreatedAt = Column(TIMESTAMP, default=func.current_timestamp())
    UpdatedAt = Column(TIMESTAMP, default=func.current_timestamp(), onupdate=func.current_timestamp())

class RolePermissions(Base):
    __tablename__ = "RolePermissions"
    RoleID = Column(Integer, ForeignKey("Roles.RoleID"), primary_key=True)
    PermissionID = Column(Integer, ForeignKey("Permissions.PermissionID"), primary_key=True)


class Users(Base):
    __tablename__ = "Users"
    UserID = Column(Integer, primary_key=True, autoincrement=True)
    AgentID = Column(Integer, ForeignKey("Agents.AgentID"), unique=True, nullable=True)
    Title = Column(Enum('Mr', 'Mrs', 'Miss', 'Dr', 'Prof', 'Other'), nullable=False)
    CorporateRight = Column(Enum('Admin', 'Manager', 'Supervisor', 'Employee'), default='Employee')
    Surname = Column(String(255), nullable=False)
    OtherNames = Column(String(255))
    Phone = Column(String(15), unique=True, nullable=False)
    Email = Column(String(255), unique=True, nullable=False)
    BranchID = Column(Integer, ForeignKey("Branches.BranchID"), nullable=True)
    Department = Column(String(255))
    PasswordExpiryTime = Column(Date, default=func.current_date() + func.interval(90, 'DAY'))
    IsDeleted = Column(Boolean, default=False)
    CreatedAt = Column(TIMESTAMP, default=func.current_timestamp())
    UpdatedAt = Column(TIMESTAMP, default=func.current_timestamp(), onupdate=func.current_timestamp())
    CreatedBy = Column(Integer, ForeignKey("Users.UserID"), nullable=True)
    password = Column(String(15), unique=True)


class UserRoles(Base):
    __tablename__ = "UserRoles"
    UserID = Column(Integer, ForeignKey("Users.UserID"), primary_key=True)
    RoleID = Column(Integer, ForeignKey("Roles.RoleID"), primary_key=True)



class Policies(Base):
    __tablename__ = "policies"
    
    PolicyID = Column(Integer, primary_key=True, autoincrement=True)
    PolicyNumber = Column(String(50), unique=True, nullable=False)
    ClientCode = Column(String(255), ForeignKey("clients.ClientCode"), nullable=False)
    AgentID = Column(Integer, ForeignKey("Agents.AgentID"))
    ProductID = Column(Integer, nullable=False)
    SumAssured = Column(DECIMAL(10, 2), nullable=False)
    Premium = Column(DECIMAL(10, 2), nullable=False)
    Term = Column(Integer, nullable=False, comment="In months")
    # How often Premium is collected: monthly | quarterly | half-yearly | annually.
    # Existing tables need: ALTER TABLE policies ADD COLUMN PaymentFrequency VARCHAR(20) NOT NULL DEFAULT 'monthly';
    PaymentFrequency = Column(String(20), nullable=False, default='monthly', server_default='monthly')
    StartDate = Column(Date, nullable=False)
    Name = Column(String(255))
    EndDate = Column(Date)
    Status = Column(Enum('Active', 'Lapsed', 'Cancelled', 'Pending', 'Expired', 
                        name='policy_status'), default='Pending')
    ApprovedBy = Column(Integer, ForeignKey("Agents.AgentID"))
    ApprovalDate = Column(Date)
    CreatedAt = Column(TIMESTAMP, default=func.current_timestamp())
    UpdatedAt = Column(TIMESTAMP, default=func.current_timestamp(), 
                      onupdate=func.current_timestamp())
    

    client = relationship("Clients", back_populates="policies")
    agent = relationship("Agents", foreign_keys=[AgentID], back_populates="policies")
    # product = relationship("InsuranceProducts", back_populates="policies")
    approver = relationship("Agents", foreign_keys=[ApprovedBy])
    

class Clients(Base):
    __tablename__ = "clients"
    
    ClientID = Column(Integer, primary_key=True, autoincrement=True)
    ClientCode = Column(String(255), unique=True, nullable=False)
    AgentID = Column(Integer, ForeignKey("Agents.AgentID"))
    BranchID = Column(Integer, ForeignKey("Branches.BranchID"))
    FirstName = Column(String(100), nullable=False)
    LastName = Column(String(100), nullable=False)
    OtherNames = Column(String(100))
    Gender = Column(Enum('Male', 'Female', 'Other', name='gender'), nullable=False)
    DateOfBirth = Column(Date)
    NationalIDNumber = Column(String(50))
    IDType = Column(Enum('National ID', 'Passport', 'Driver License', 'Voter ID', 'Other', 
                        name='id_type'))
    IDNumber = Column(String(50))
    PhoneNumber = Column(String(15), nullable=False)
    Email = Column(String(100))
    Nationality = Column(String(50))
    ResidentialAddress = Column(Text)
    City = Column(String(100))
    CountryCode = Column(String(3), ForeignKey("countries.CountryCode"))
    Occupation = Column(String(100))
    Status = Column(Enum('Active', 'Inactive', name='client_status'), default='Active')
    CreatedAt = Column(TIMESTAMP, default=func.current_timestamp())
    UpdatedAt = Column(TIMESTAMP, default=func.current_timestamp(), 
                      onupdate=func.current_timestamp())
 
    agent = relationship("Agents", back_populates="clients")
    branch = relationship("Branches", back_populates="clients")
    country = relationship("Countries", back_populates="clients")
    policies = relationship("Policies", back_populates="client")



class PoliciesDependant(Base):
    __tablename__ = "dependant"
    id = Column(Integer, primary_key=True, index=True)
    ClientID = Column(String(255), nullable=False)
    agent = Column(String(255))
    full_name = Column(String(255))
    date_of_birth = Column(String(255))
    relation_type = Column(String(255))
    phone_number = Column(String(255))
    allocation_percentage = Column(DECIMAL(5, 2))
    policy_id = Column(Integer, ForeignKey("policies.PolicyID"))


class PolicyBenefits(Base):
    __tablename__ = "policy_benefits"
    id = Column(Integer, primary_key=True, autoincrement=True)
    PolicyID = Column(Integer, ForeignKey("policies.PolicyID"), nullable=False)
    ClientCode = Column(String(255), ForeignKey("clients.ClientCode"), nullable=False)
    BenefitText = Column(String(500), nullable=False)
    CreatedAt = Column(DateTime, default=datetime.utcnow)

# class InsuranceProducts(Base):
#     __tablename__ = "insuranceproducts"
    
#     ProductID = Column(Integer, primary_key=True, autoincrement=True)
#     ProductCode = Column(String(20), unique=True, nullable=False)
#     Name = Column(String(100), nullable=False)
#     CategoryID = Column(Integer, ForeignKey("insurancecategories.CategoryID"), nullable=False)
#     SubCategoryID = Column(Integer, ForeignKey("insurancesubcategories.SubCategoryID"), nullable=False)
#     SumAssured = Column(DECIMAL(10, 2), nullable=False)
#     Premium = Column(DECIMAL(10, 2), nullable=False)
#     Term = Column(Integer, nullable=False, comment="In months")
#     Status = Column(Enum('Active', 'Inactive', name='product_status'), 
#                   default='Active', nullable=False)
#     CreatedAt = Column(TIMESTAMP, default=func.current_timestamp())
#     UpdatedAt = Column(TIMESTAMP, default=func.current_timestamp(), 
#                       onupdate=func.current_timestamp())
    
#     category = relationship("InsuranceCategories", back_populates="products")
#     subcategory = relationship("InsuranceSubCategories", back_populates="products")
#     policies = relationship("Policies", back_populates="product")
#     # product = relationship("Product", back_populates="insurance_product", uselist=False)


# class InsuranceCategories(Base):
#     __tablename__ = "insurancecategories"
    
#     CategoryID = Column(Integer, primary_key=True, autoincrement=True)
#     Name = Column(String(100), nullable=False)
#     Status = Column(Enum('Active', 'Inactive', name='category_status'), 
#                   default='Active', nullable=False)
    
#     subcategories = relationship("InsuranceSubCategories", back_populates="category",
#                               cascade="all, delete-orphan")
#     products = relationship("InsuranceProducts", back_populates="category")

# class InsuranceSubCategories(Base):
#     __tablename__ = "insurancesubcategories"
    
#     SubCategoryID = Column(Integer, primary_key=True, autoincrement=True)
#     CategoryID = Column(Integer, ForeignKey("insurancecategories.CategoryID", 
#                                          ondelete="CASCADE"), nullable=False)
#     Name = Column(String(100), nullable=False)
#     Status = Column(Enum('Active', 'Inactive', name='subcategory_status'), 
#                   default='Active', nullable=False)
    
#     category = relationship("InsuranceCategories", back_populates="subcategories")
#     products = relationship("InsuranceProducts", back_populates="subcategory")




class Countries(Base):
    __tablename__ = "countries"
    
    CountryCode = Column(CHAR(3), primary_key=True)
    CountryName = Column(String(200), nullable=False)
    Code = Column(CHAR(10))
    
    clients = relationship("Clients", back_populates="country")



class CallBackPayments(Base):
    __tablename__ = "callback_pay"
    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String(255))
    uniwalletTransactionId = Column(String(255))
    networkTransactionId = Column(String(255))
    refNo = Column(String(255))
    productId = Column(String(255))
    msisdn = Column(String(255))
    amount = Column(String(255))
    narration = Column(String(255))
    timestamp = Column(String(255))
    responseCode = Column(String(255))
    responseMessage = Column(String(255))
    network = Column(String(255))
    transflowId = Column(String(255))

class ClientPolicySubmit(Base):
    __tablename__ = "client_policies"
    id = Column(String(255), primary_key=True, index=True)
    cli_id = Column(String(255), unique=True, index=True)
    client_info = Column(JSON)
    dependants = Column(JSON, nullable=True)
    policy = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)

class LoginScheme(Base):
    __tablename__ = "login_scheme"
    id = Column(Integer, primary_key=True, index=True)
    ClientID = Column(String(255), nullable=False)
    login_at = Column(DateTime, default=datetime.utcnow)
    logout_at = Column(DateTime, nullable=True)

class BankDeductionDB(Base):
    __tablename__ = "bank_deductions"
    
    id = Column(Integer, primary_key=True, index=True)
    bank_name = Column(String(255), nullable=False)
    bank_account_number = Column(String(255), nullable=False)
    branch = Column(String(255), nullable=False)
    policy_id = Column(Integer, nullable=False)
    client_id = Column(Integer, nullable=False)
    under_agent = Column(Integer, nullable=False) 
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class GovernmentDeductionDB(Base):
    __tablename__ = "government_deductions"
    
    id = Column(Integer, primary_key=True, index=True)

    staff_id = Column(String(225), nullable=False)  
    staff_name = Column(String(255), nullable=False) 
    institution_name = Column(String(255), nullable=False) 
    amount = Column(Float, nullable=False) 
    

    policy_id = Column(String(255), nullable=False)  
    client_id = Column(String(255), nullable=False)  
    under_agent = Column(String(255), nullable=False)  
    

    deduction_date = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class PaymentHistory(Base):
    __tablename__ = 'payment_history'

    id = Column(Integer, primary_key=True, index=True)
    policy_id = Column(Integer, ForeignKey('policies.PolicyID'), nullable=False)  
    amount = Column(Numeric(10, 2), nullable=False)  
    currency = Column(String(3), default='USD') 
    payment_method = Column(String(50))  
    transaction_id = Column(String(100), unique=True) 
    status = Column(String(20), default='pending')  
    description = Column(String(255))  
    created_at = Column(DateTime(timezone=True), server_default=func.now())  
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())  
    
class Mandate(Base):
    __tablename__ = "mandates"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(String(255), nullable=False)
    responseCode = Column(String(255), nullable=False)
    responseMessage = Column(String(255), nullable=False)
    merchantId = Column(String(255), nullable=False)
    productId = Column(String(255), nullable=False)
    mandateId = Column(String(255), nullable=True)
    clientPhone = Column(String(255), nullable=False)
    thirdPartyReferenceNo = Column(String(255), nullable=False)
    create_at = Column(DateTime, default=func.now())


# ============= Payment gateway webhook receivers (Transflow / Uniwallet) =============

class MandateCallback(Base):
    __tablename__ = "mandate_callback"
    id = Column(Integer, primary_key=True, index=True)
    responseCode = Column(String(255), nullable=False)
    responseMessage = Column(String(255), nullable=False)
    merchantId = Column(String(255), nullable=False)
    productId = Column(String(255), nullable=False)
    mandateId = Column(String(255), nullable=True)
    clientPhone = Column(String(255), nullable=False)
    thirdPartyReferenceNo = Column(String(255), nullable=False)
    create_at = Column(DateTime, default=func.now())


class UniwalletCallback(Base):
    __tablename__ = "uniwallet_callback"
    id = Column(Integer, primary_key=True, autoincrement=True)
    uniwalletTransactionId = Column(String(255))
    networkTransactionId = Column(String(255))
    refNo = Column(String(255))
    productId = Column(String(255))
    msisdn = Column(String(255))
    amount = Column(String(255))
    narration = Column(String(255))
    timestamp = Column(String(255))
    responseCode = Column(String(255))
    responseMessage = Column(String(255))
    network = Column(String(255))
    transflowId = Column(String(255))
    created_at = Column(DateTime, default=func.now())


class MandateTransactionCallback(Base):
    __tablename__ = "mandate_transaction_callback"
    id = Column(Integer, primary_key=True, autoincrement=True)
    responseCode = Column(String(255))
    responseMessage = Column(String(255))
    momTransactionId = Column(String(255))
    debitOrderTransactionId = Column(String(255))
    merchantId = Column(String(255))
    productId = Column(String(255))
    mandateId = Column(String(255))
    clientPhone = Column(String(255))
    amount = Column(String(255))
    thirdPartyReferenceNo = Column(String(255))
    created_at = Column(DateTime, default=func.now())



class PaymentCredit(Base):
    """Payment notifications received on POST /payments/credit. Every notification is kept,
    including rejected ones, so unallocated money can be followed up."""
    __tablename__ = "payment_credits"
    id = Column(Integer, primary_key=True, autoincrement=True)
    transaction_id = Column(String(100), unique=True, nullable=False)
    policy_number = Column(String(50), nullable=False, index=True)
    policy_id = Column(Integer, ForeignKey("policies.PolicyID"), nullable=True)
    amount = Column(Numeric(10, 2), nullable=False)
    phone_number = Column(String(20), nullable=False)
    trans_date = Column(String(50), nullable=False)  # stored as sent by the caller
    status = Column(String(20), nullable=False)  # credited | rejected
    note = Column(String(255))
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class PolicyFamilyPlan(Base):
    """The family size a family-plan policy (Ebusua Health) was bought for. Its tier, and so its
    premium, is fixed at purchase; family members are added into these slots later."""
    __tablename__ = "policy_family_plans"
    policy_id = Column(Integer, ForeignKey("policies.PolicyID"), primary_key=True)
    plan_type = Column(String(50), nullable=False)  # e.g. OAK
    tier_value = Column(String(20), nullable=False)
    tier_name = Column(String(50), nullable=False)  # e.g. M+3
    family_slots = Column(Integer, nullable=False)  # members allowed besides the policy holder
    created_at = Column(DateTime, default=func.now())


class PolicyFamilyMember(Base):
    """A family member covered by a family-plan policy. member_number is the policy number plus
    a running number (POL26900412-1, -2, ...); numbers are never reused, even after a removal."""
    __tablename__ = "policy_family_members"
    id = Column(Integer, primary_key=True, autoincrement=True)
    policy_id = Column(Integer, ForeignKey("policies.PolicyID"), nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    member_number = Column(String(80), unique=True, nullable=False)
    relation = Column(String(20), nullable=False)  # spouse | child | parent | other
    full_name = Column(String(255), nullable=False)
    date_of_birth = Column(Date, nullable=False)
    ghana_card = Column(String(50))  # required for adults, optional for children
    phone_number = Column(String(20))
    status = Column(String(20), nullable=False, default="Active")  # Active | Removed
    created_at = Column(DateTime, default=func.now())
    removed_at = Column(DateTime)


class PolicyPaymentMethod(Base):
    """How a policy is paid: by bank or through the Controller (government payroll deduction).
    Client and policy details are copied in as they were when the method was set. Setting a new
    method marks the previous one Replaced, so the history is kept."""
    __tablename__ = "policy_payment_methods"
    id = Column(Integer, primary_key=True, autoincrement=True)
    policy_id = Column(Integer, ForeignKey("policies.PolicyID"), nullable=False, index=True)
    payment_mode = Column(String(20), nullable=False)  # bank | controller
    status = Column(String(20), nullable=False, default="Active")  # Active | Replaced

    # Client
    client_code = Column(String(255), nullable=False, index=True)
    client_name = Column(String(255))
    phone_number = Column(String(20), nullable=False)
    ghana_card = Column(String(50))

    # Policy
    policy_number = Column(String(50), nullable=False, index=True)
    product_name = Column(String(255))
    premium = Column(Numeric(10, 2))
    frequency = Column(String(20))

    # Bank
    bank_name = Column(String(100))
    bank_branch = Column(String(100))
    account_name = Column(String(255))
    account_number = Column(String(50))

    # Controller
    staff_id = Column(String(50))
    employer = Column(String(255))
    management_unit = Column(String(255))

    created_at = Column(DateTime, default=func.now())
    replaced_at = Column(DateTime)
