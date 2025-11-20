from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Dict, Any, List
from datetime import datetime, timedelta
import json
import httpx
import hashlib
from app.setup.database import get_db
from app.models.migration import (
    Clients, Policies, Agents, 
    PoliciesDependant, PaymentHistory, Mandate,
    Countries, Branches, Commissions, GovernmentDeductionDB, BankDeductionDB, ClientPIN
)
from app.schemas.ussd_schemas import *
from app.config.addition import make_mandate_payment, send_sms

router = APIRouter(prefix="/ussd")

ussd_sessions = {}

def get_ussd_session(session_id: str) -> Dict[str, Any]:
    return ussd_sessions.get(session_id, {})

def set_ussd_session(session_id: str, data: Dict[str, Any]):
    ussd_sessions[session_id] = data

def clear_ussd_session(session_id: str):
    if session_id in ussd_sessions:
        del ussd_sessions[session_id]

def hash_pin(pin: str) -> str:

    return hashlib.sha256(pin.encode()).hexdigest()

def verify_pin(stored_pin_hash: str, provided_pin: str) -> bool:
    return stored_pin_hash == hash_pin(provided_pin)


async def validate_agent_code(agent_code: str, db: Session) -> Dict[str, Any]:
    agent = db.query(Agents).filter(
        Agents.agent_code == agent_code,
        Agents.Status == 'Active'
    ).first()
    
    if not agent:
        return {"is_valid": False, "message": "Invalid or inactive agent code"}
    
    return {
        "is_valid": True,
        "agent_id": agent.AgentID,
        "agent_name": f"{agent.OtherNames}",
        "message": "Agent validated successfully"
    }

async def create_mandate_for_policy(
    client_phone: str,
    premium_amount: float,
    policy_number: str,
    db: Session
) -> Dict[str, Any]:
    try:
        start_date = datetime.now().strftime("%Y-%m-%d")
        end_date = (datetime.now() + timedelta(days=365 * 5)).strftime("%Y-%m-%d") 
        debit_day = "1"
        
        mandate_response = await make_mandate_payment(
            client_phone=client_phone,
            amount_to_debit=str(premium_amount),
            frequency_type="MONTHLY",
            frequency="1",
            start_date=start_date,
            end_date=end_date,
            debit_day=debit_day,
            ref_no=policy_number
        )
        
        mandate_record = Mandate(
            client_id=client_phone,
            responseCode=mandate_response.get("responseCode", "0000"),
            responseMessage=mandate_response.get("responseMessage", "Success"),
            merchantId=mandate_response.get("merchantId", ""),
            productId=mandate_response.get("productId", ""),
            mandateId=mandate_response.get("mandateId", ""),
            clientPhone=client_phone,
            thirdPartyReferenceNo=policy_number
        )
        
        db.add(mandate_record)
        db.commit()
        
        return {
            "status": "success",
            "mandate_id": mandate_response.get("mandateId"),
            "response_code": mandate_response.get("responseCode"),
            "response_message": mandate_response.get("responseMessage")
        }
        
    except Exception as e:
        db.rollback()
        return {
            "status": "error",
            "message": f"Mandate creation failed: {str(e)}"
        }

@router.get("/terms-and-conditions", response_model=TermsResponse)
async def get_terms_and_conditions():
    return {
        "status": "success",
        "terms_url": "www.decision-insurance-policy",
        "message": "Full terms and conditions available at www.decision-insurance-policy"
    }


@router.post("/registration", response_model=CustomerRegistrationResponse)
async def register_member(
    customer: RegisterRequest,
    db: Session = Depends(get_db)
):
    try:
        existing_client = db.query(Clients).filter(
            Clients.PhoneNumber == customer.phonenumber
        ).first()
        
        if existing_client:
            return {
                "status": "error",
                "message": "Member already registered with this phone number"
            }

        agent_code = customer.agent_code if customer.agent_code else "EHI_0000_C"
        agent_validation = await validate_agent_code(agent_code, db)
        
        if not agent_validation["is_valid"]:
            return {
                "status": "error",
                "message": agent_validation["message"]
            }
        new_client = Clients(
            ClientCode=f"CLI{customer.phonenumber}{datetime.now().strftime('%H%M%S')}",
            AgentID=agent_validation["agent_id"],
            PhoneNumber=customer.phonenumber,
            FirstName="",
            LastName="",
            NationalIDNumber=customer.ghana_card,
            IDType="National ID",
            Gender='Other',
            Status='Active',
            CreatedAt=datetime.now()
        )
        
        db.add(new_client)
        db.commit()

        try:
            sms_message = f"Client registration successful! Client Code: {new_client.ClientCode}. Please create a PIN and purchase a policy to complete registration."
            await send_sms(customer.phonenumber, sms_message)
        except Exception as sms_error:
            print(f"SMS sending failed: {sms_error}")

        return {
            "status": "success",
            "message": "Client registration successful. Please create PIN and purchase policy to complete registration.",
            "client_code": new_client.ClientCode,
            "policy_number": None,
            "premium": None,
            "product_name": None,
            "sum_assured": None,
            "term": None,
            "mandate_id": None
        }
        
    except Exception as e:
        db.rollback()
        return {
            "status": "error",
            "message": f"Registration failed: {str(e)}"
        }

@router.post("/registration/agent", response_model=CustomerRegistrationResponse)
async def agent_register_member(
    customer: AgentRegisterRequest,
    db: Session = Depends(get_db)
):
    try:
        existing_client = db.query(Clients).filter(
            Clients.PhoneNumber == customer.phonenumber
        ).first()
        
        if existing_client:
            return {
                "status": "error",
                "message": "Member already registered with this phone number"
            }

    
        agent_validation = await validate_agent_code(customer.agent_code, db)
        
        if not agent_validation["is_valid"]:
            return {
                "status": "error",
                "message": agent_validation["message"]
            }

        new_client = Clients(
            ClientCode=f"CLI{customer.phonenumber}{datetime.now().strftime('%H%M%S')}",
            AgentID=agent_validation["agent_id"],
            PhoneNumber=customer.phonenumber,
            FirstName="",
            LastName="", 
            NationalIDNumber=customer.ghana_card,
            IDType="National ID",
            Gender='Other',
            Status='Active',
            CreatedAt=datetime.now()
        )
        
        db.add(new_client)
        db.commit()

        try:
            sms_message = f"Client registration successful! Client Code: {new_client.ClientCode}. Agent: {agent_validation['agent_name']}. Please create a PIN and purchase a policy to complete registration."
            await send_sms(customer.phonenumber, sms_message)
        except Exception as sms_error:
            print(f"SMS sending failed: {sms_error}")

        return {
            "status": "success",
            "message": "Client registration successful. Please create PIN and purchase policy to complete registration.",
            "client_code": new_client.ClientCode,
            "policy_number": None,
            "premium": None,
            "product_name": None,
            "sum_assured": None,
            "term": None,
            "mandate_id": None
        }
        
    except Exception as e:
        db.rollback()
        return {
            "status": "error",
            "message": f"Registration failed: {str(e)}"
        }


from app.service.enum import AgeGroup



@router.get("/product/age_group", response_model=AgeGroupResponse)
async def get_age_group():
    return {
        "young_age": AgeGroup.YOUNG,
        "middle_age": AgeGroup.MIDDLE_AGED,
        "senior_age": AgeGroup.SENIOR
    }

@router.post("/policy/create", response_model=CustomerRegistrationResponse)
async def create_policy(
    client_code: str,
    product_name: str,
    age_group: str,
    db: Session = Depends(get_db)
):
    try:
        client = db.query(Clients).filter(
            Clients.ClientCode == client_code
        ).first()
        
        if not client:
            return {
                "status": "error",
                "message": "Client not found. Please register first."
            }

        existing_policy = db.query(Policies).filter(
            Policies.ClientCode == client_code,
            Policies.Status == 'Active'
        ).first()
        
        if existing_policy:
            return {
                "status": "error",
                "message": "Client already has an active policy"
            }

        async with httpx.AsyncClient() as client_http:
            try:
                products_response = await client_http.get(
                    "http://api.equityhealthinsurance.com/insurance/insurance-products/",
                    timeout=30.0
                )
                
                if products_response.status_code != 200:
                    return {
                        "status": "error",
                        "message": "Failed to fetch insurance products from external service"
                    }
                
                products_data = products_response.json()
                
                product = None
                for prod in products_data:
                    if prod.get("name", "").lower() == product_name.lower():
                        product = prod
                        break
                
                if not product:
                    return {
                        "status": "error",
                        "message": "Invalid product name"
                    }
                
                product_details_response = await client_http.get(
                    f"https://salesapp.equityhealthinsurance.com/insurance/products/insurance/product-details/{product.get('_id')}",
                    timeout=30.0
                )
                
                product_details = {}
                if product_details_response.status_code == 200:
                    product_details = product_details_response.json()
                
            except httpx.RequestError as e:
                return {
                    "status": "error",
                    "message": f"Failed to connect to insurance service: {str(e)}"
                }

        product_name = product.get("name", "Unknown Product")
        product_code = product.get("productCode", "")
        premium = product.get("premium", 0.0)
        sum_assured = product.get("sum_assured", 0.0)
        term = product.get("term", 12)

        calculated_premium = premium
        if age_group and product_details.get("premium_structures"):
            premium_structures = product_details["premium_structures"]
            for structure in premium_structures:
                if structure.get("premium_type") == "individual" and structure.get("tiers"):
                    for tier in structure["tiers"]:
                        if tier.get("tier_name") == "Monthly Premium per person":
                            calculated_premium = tier.get("premium_amount", premium)
                            break
        
        

        new_policy = Policies(
            PolicyNumber=f"POL{datetime.now().strftime('%Y%m%d%H%M%S')}",
            ClientCode=client_code,
            AgentID=client.AgentID,
            ProductID=product.get('_id'),
            SumAssured=sum_assured,
            Premium=calculated_premium,
            Term=term,
            StartDate=datetime.now().date(),
            Status='Pending',
            Name=product_name
        )
        
        db.add(new_policy)
        db.flush()

        if (age_group == AgeGroup.MIDDLE_AGED) or (age_group == AgeGroup.SENIOR):
            total = (calculated_premium / 2) + calculated_premium
            
        total = calculated_premium 
            
        mandate_result = await create_mandate_for_policy(
            client_phone=client.PhoneNumber,
            premium_amount=total,
            policy_number=new_policy.PolicyNumber,
            db=db
        )

        db.commit()

        try:
            sms_message = f"Policy created successfully! Policy: {new_policy.PolicyNumber}, Premium: GHS {calculated_premium:.2f}/month, Sum Assured: GHS {sum_assured:.2f}"
            await send_sms(client.PhoneNumber, sms_message)
        except Exception as sms_error:
            print(f"SMS sending failed: {sms_error}")

        return {
            "status": "success",
            "message": "Policy created successfully.",
            "policy_number": new_policy.PolicyNumber,
            "premium": float(total),
            "product_name": product_name,
            "sum_assured": float(sum_assured),
            "term": term,
            "mandate_id": mandate_result.get("mandate_id"),
            "client_code": client_code
        }
        
    except Exception as e:
        db.rollback()
        return {
            "status": "error",
            "message": f"Policy creation failed: {str(e)}"
        }

@router.post("/pin/create")
async def create_pin(
    client_code: str,
    pin: str,
    db: Session = Depends(get_db)
):
    try:
        client = db.query(Clients).filter(
            Clients.ClientCode == client_code
        ).first()
        
        if not client:
            return {
                "status": "error",
                "message": "Client not found"
            }

        existing_pin = db.query(ClientPIN).filter(
            ClientPIN.client_code == client_code
        ).first()
        
        if existing_pin:
            return {
                "status": "error",
                "message": "PIN already exists for this client"
            }

        if not pin.isdigit() or len(pin) != 4:
            return {
                "status": "error",
                "message": "PIN must be 4 digits"
            }

        new_pin = ClientPIN(
            client_code=client_code,
            pin_hash=hash_pin(pin),
            is_active=True
        )
        
        db.add(new_pin)
        db.commit()

        return {
            "status": "success",
            "message": "PIN created successfully"
        }
        
    except Exception as e:
        db.rollback()
        return {
            "status": "error",
            "message": f"PIN creation failed: {str(e)}"
        }

@router.post("/pin/verify")
async def verify_pin_endpoint(
    client_code: str,
    pin: str,
    db: Session = Depends(get_db)
):
    try:
        client = db.query(Clients).filter(
            Clients.ClientCode == client_code
        ).first()
        
        if not client:
            return {
                "status": "error",
                "message": "Client not found"
            }

        pin_record = db.query(ClientPIN).filter(
            ClientPIN.client_code == client_code
        ).first()
        
        if not pin_record:
            return {
                "status": "error",
                "message": "PIN not found for this client"
            }

        if not pin_record.is_active:
            return {
                "status": "error",
                "message": "PIN is inactive"
            }

        if pin_record.failed_attempts >= 3:
            # Check if 30 minutes have passed since last attempt
            if pin_record.last_attempt and (datetime.utcnow() - pin_record.last_attempt).total_seconds() < 1800:
                return {
                    "status": "error",
                    "message": "Account locked due to too many failed attempts. Try again after 30 minutes."
                }
            else:
                pin_record.failed_attempts = 0

        if verify_pin(pin_record.pin_hash, pin):

            pin_record.failed_attempts = 0
            pin_record.last_attempt = datetime.utcnow()
            db.commit()
            
            return {
                "status": "success",
                "message": "PIN verified successfully"
            }
        else:
            # Increment failed attempts
            pin_record.failed_attempts += 1
            pin_record.last_attempt = datetime.utcnow()
            db.commit()
            
            remaining_attempts = 3 - pin_record.failed_attempts
            return {
                "status": "error",
                "message": f"Invalid PIN. {remaining_attempts} attempts remaining."
            }
        
    except Exception as e:
        db.rollback()
        return {
            "status": "error",
            "message": f"PIN verification failed: {str(e)}"
        }

@router.post("/pin/reset")
async def reset_pin(
    client_code: str,
    new_pin: str,
    db: Session = Depends(get_db)
):
  
    try:
        client = db.query(Clients).filter(
            Clients.ClientCode == client_code
        ).first()
        
        if not client:
            return {
                "status": "error",
                "message": "Client not found"
            }

        pin_record = db.query(ClientPIN).filter(
            ClientPIN.client_code == client_code
        ).first()
        
        if not pin_record:
            return {
                "status": "error",
                "message": "PIN not found for this client"
            }

        if not new_pin.isdigit() or len(new_pin) != 4:
            return {
                "status": "error",
                "message": "PIN must be 4 digits"
            }

        pin_record.pin_hash = hash_pin(new_pin)
        pin_record.failed_attempts = 0
        pin_record.is_active = True
        pin_record.updated_at = datetime.utcnow()
        
        db.commit()

        return {
            "status": "success",
            "message": "PIN reset successfully"
        }
        
    except Exception as e:
        db.rollback()
        return {
            "status": "error",
            "message": f"PIN reset failed: {str(e)}"
        }




@router.get("/products")
async def get_insurance_products():
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "http://api.equityhealthinsurance.com/insurance/insurance-products/",
                timeout=30.0
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Failed to fetch insurance products"
                )
            
            products_data = response.json()
            
            formatted_products = []
            for product in products_data:
                formatted_products.append({
                    "id": product.get("_id"),
                    "product_code": product.get("productCode"),
                    "name": product.get("name"),
                    "premium": product.get("premium"),
                    "sum_assured": product.get("sum_assured"),
                    "term": product.get("term"),
                    "status": product.get("status")
                })
            
            return {
                "status": "success",
                "products": formatted_products
            }
            
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Insurance service unavailable: {str(e)}"
        )

@router.get("/products/{product_id}")
async def get_insurance_product_details(product_id: str):
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://salesapp.equityhealthinsurance.com/insurance/products/insurance/product-details/{product_id}",
                timeout=30.0
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not found"
                )
            
            product_details = response.json()
            
            return {
                "status": "success",
                "product_details": product_details
            }
            
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Insurance service unavailable: {str(e)}"
        )

@router.get("/products/{product_name}/plans")
async def get_product_plans(product_name: str):
    
    try:
        async with httpx.AsyncClient() as client:
            
            products_response = await client.get(
                "http://api.equityhealthinsurance.com/insurance/insurance-products/",
                timeout=30.0
            )
            
            if products_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Failed to fetch insurance products"
                )
            
            products_data = products_response.json()
            
            target_product = None
            for product in products_data:
                if product.get("name", "").lower() == product_name.lower():
                    target_product = product
                    break
            
            if not target_product:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not found"
                )
            
            product_id = target_product.get("_id")
            
            response = await client.get(
                f"https://salesapp.equityhealthinsurance.com/insurance/products/insurance/product-details/{product_id}",
                timeout=30.0
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product details not found"
                )
            
            product_details = response.json()
            premium_structures = product_details.get("premium_structures", [])
            
            plans = []
            
            for structure in premium_structures:
                premium_type = structure.get("premium_type", "")
                tiers = structure.get("tiers", [])
                
                if len(premium_structures) == 1 and len(tiers) > 1:
                    for tier in tiers:
                        plans.append({
                            "plan_name": tier.get("tier_name"),
                            "premium_type": premium_type,
                            "premium_amount": tier.get("premium_amount"),
                            "sum_assured": tier.get("sum_assured"),
                            "tier_value": tier.get("tier_value"),
                            "is_tier": True
                        })
                elif len(premium_structures) > 1:
                    plans.append({
                        "plan_name": f"{premium_type.replace('_', ' ').title()} Plan",
                        "premium_type": premium_type,
                        "base_premium": structure.get("base_premium"),
                        "min_sum_assured": structure.get("min_sum_assured"),
                        "max_sum_assured": structure.get("max_sum_assured"),
                        "is_tier": False,
                        "tiers_count": len(tiers)
                    })

                else:
                    plans.append({
                        "plan_name": f"{premium_type.replace('_', ' ').title()} Plan",
                        "premium_type": premium_type,
                        "base_premium": structure.get("base_premium"),
                        "min_sum_assured": structure.get("min_sum_assured"),
                        "max_sum_assured": structure.get("max_sum_assured"),
                        "is_tier": False
                    })
            
            return {
                "status": "success",
                "product_name": product_name,
                "plans": plans
            }
            
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Insurance service unavailable: {str(e)}"
        )

@router.get("/products/{product_name}/plans/{plan_name}/tiers")
async def get_plan_tiers(product_name: str, plan_name: str):
    """Get tiers for a specific plan using product name and plan name"""
    try:
        async with httpx.AsyncClient() as client:
            products_response = await client.get(
                "http://api.equityhealthinsurance.com/insurance/insurance-products/",
                timeout=30.0
            )
            
            if products_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Failed to fetch insurance products"
                )
            
            products_data = products_response.json()
            
            target_product = None
            for product in products_data:
                if product.get("name", "").lower() == product_name.lower():
                    target_product = product
                    break
            
            if not target_product:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not found"
                )
            
            product_id = target_product.get("_id")
            
            response = await client.get(
                f"https://salesapp.equityhealthinsurance.com/insurance/products/insurance/product-details/{product_id}",
                timeout=30.0
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product details not found"
                )
            
            product_details = response.json()
            premium_structures = product_details.get("premium_structures", [])
            
            target_structure = None
            target_tier = None
            
            for structure in premium_structures:
                premium_type = structure.get("premium_type", "")
                tiers = structure.get("tiers", [])
                

                structure_plan_name = f"{premium_type.replace('_', ' ').title()} Plan"
                if structure_plan_name.lower() == plan_name.lower():
                    target_structure = structure
                    break
                
                for tier in tiers:
                    if tier.get("tier_name", "").lower() == plan_name.lower():
                        target_tier = tier
                        target_structure = structure
                        break
                
                if target_tier:
                    break
            
            if not target_structure:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Plan not found"
                )
            

            if target_tier:
                return {
                    "status": "success",
                    "product_name": product_name,
                    "plan_name": plan_name,
                    "tiers": [target_tier],
                    "is_single_tier": True
                }
            
            tiers = target_structure.get("tiers", [])
            
            return {
                "status": "success",
                "product_name": product_name,
                "plan_name": plan_name,
                "tiers": tiers,
                "is_single_tier": False
            }
            
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Insurance service unavailable: {str(e)}"
        )

@router.get("/products/{product_name}/tiers")
async def get_all_product_tiers(product_name: str):
    try:
        async with httpx.AsyncClient() as client:
            products_response = await client.get(
                "http://api.equityhealthinsurance.com/insurance/insurance-products/",
                timeout=30.0
            )
            
            if products_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Failed to fetch insurance products"
                )
            
            products_data = products_response.json()
            target_product = None
            for product in products_data:
                if product.get("name", "").lower() == product_name.lower():
                    target_product = product
                    break
            
            if not target_product:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not found"
                )
            
            product_id = target_product.get("_id")
            
            response = await client.get(
                f"https://salesapp.equityhealthinsurance.com/insurance/products/insurance/product-details/{product_id}",
                timeout=30.0
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product details not found"
                )
            
            product_details = response.json()
            premium_structures = product_details.get("premium_structures", [])
            
            all_tiers = []
            for structure in premium_structures:
                premium_type = structure.get("premium_type", "")
                tiers = structure.get("tiers", [])
                
                for tier in tiers:
                    tier_data = {
                        "tier_name": tier.get("tier_name"),
                        "premium_type": premium_type,
                        "premium_amount": tier.get("premium_amount"),
                        "sum_assured": tier.get("sum_assured"),
                        "tier_value": tier.get("tier_value")
                    }
                    all_tiers.append(tier_data)
            
            return {
                "status": "success",
                "product_name": product_name,
                "tiers": all_tiers
            }
            
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Insurance service unavailable: {str(e)}"
        )

@router.get("/products/{product_name}/plan/{tier_name}")
async def get_specific_tier_details(product_name: str, tier_name: str):
    try:
        async with httpx.AsyncClient() as client:
            products_response = await client.get(
                "http://api.equityhealthinsurance.com/insurance/insurance-products/",
                timeout=30.0
            )
            
            if products_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Failed to fetch insurance products"
                )
            
            products_data = products_response.json()
            
            target_product = None
            for product in products_data:
                if product.get("name", "").lower() == product_name.lower():
                    target_product = product
                    break
            
            if not target_product:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not found"
                )
            
            product_id = target_product.get("_id")
            
            response = await client.get(
                f"https://salesapp.equityhealthinsurance.com/insurance/products/insurance/product-details/{product_id}",
                timeout=30.0
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product details not found"
                )
            
            product_details = response.json()
            premium_structures = product_details.get("premium_structures", [])
            
            target_tier = None
            for structure in premium_structures:
                tiers = structure.get("tiers", [])
                for tier in tiers:
                    if tier.get("tier_name", "").lower() == tier_name.lower():
                        target_tier = tier
                        target_tier["premium_type"] = structure.get("premium_type")
                        break
                if target_tier:
                    break
            
            if not target_tier:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Tier not found"
                )
            
            return {
                "status": "success",
                "product_name": product_name,
                "tier_name": tier_name,
                "tier_details": target_tier
            }
            
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Insurance service unavailable: {str(e)}"
        )

@router.get("/products/{product_id}/tiers")
async def get_all_product_tiers(product_id: str):
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://salesapp.equityhealthinsurance.com/insurance/products/insurance/product-details/{product_id}",
                timeout=30.0
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not found"
                )
            
            product_details = response.json()
            premium_structures = product_details.get("premium_structures", [])
            
            all_tiers = []
            for structure in premium_structures:
                premium_type = structure.get("premium_type", "")
                tiers = structure.get("tiers", [])
                
                for tier in tiers:
                    tier_data = {
                        "tier_id": tier.get("_id"),
                        "tier_name": tier.get("tier_name"),
                        "premium_type": premium_type,
                        "premium_amount": tier.get("premium_amount"),
                        "sum_assured": tier.get("sum_assured"),
                        "tier_value": tier.get("tier_value"),
                        "structure_id": structure.get("_id")
                    }
                    all_tiers.append(tier_data)
            
            return {
                "status": "success",
                "product_id": product_id,
                "product_name": product_details.get("insurance_product", {}).get("name"),
                "tiers": all_tiers
            }
            
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Insurance service unavailable: {str(e)}"
        )

@router.get("/products/name/{product_name}")
async def get_product_by_name(product_name: str):
    """Get product details by product name"""
    try:
        async with httpx.AsyncClient() as client:
            products_response = await client.get(
                "http://api.equityhealthinsurance.com/insurance/insurance-products/",
                timeout=30.0
            )
            
            if products_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Failed to fetch insurance products"
                )
            
            products_data = products_response.json()
            
            target_product = None
            for product in products_data:
                if product.get("name", "").lower() == product_name.lower():
                    target_product = product
                    break
            
            if not target_product:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not found"
                )
            
            product_id = target_product.get("_id")
            details_response = await client.get(
                f"https://salesapp.equityhealthinsurance.com/insurance/products/insurance/product-details/{product_id}",
                timeout=30.0
            )
            
            if details_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product details not found"
                )
            
            product_details = details_response.json()
            
            return {
                "status": "success",
                "product": target_product,
                "product_details": product_details
            }
            
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Insurance service unavailable: {str(e)}"
        )
        
@router.get("/lookup/phone/{phone_number}")
async def lookup_by_phone(
    phone_number: str,
    db: Session = Depends(get_db)
):
    client = db.query(Clients).filter(
        Clients.PhoneNumber == phone_number
    ).first()
    
    if not client:
        return {
            "status": "error",
            "message": "Member not found"
        }
    
    policies = db.query(Policies).filter(
        Policies.ClientCode == client.ClientCode
    ).all()
    
    return {
        "status": "success",
        "client": {
            "client_code": client.ClientCode,
            "first_name": client.FirstName,
            "last_name": client.LastName,
            "phone_number": client.PhoneNumber,
            "status": client.Status
        },
        "policies": [
            {
                "policy_number": policy.PolicyNumber,
                "premium": float(policy.Premium),
                "status": policy.Status,
                "start_date": policy.StartDate.isoformat() if policy.StartDate else None
            }
            for policy in policies
        ]
    }

@router.get("/lookup/policy/{policy_number}")
async def lookup_by_policy(
    policy_number: str,
    db: Session = Depends(get_db)
):
    """Lookup member by policy number"""
    policy = db.query(Policies).filter(
        Policies.PolicyNumber == policy_number
    ).first()
    
    if not policy:
        return {
            "status": "error",
            "message": "Policy not found"
        }
    
    client = db.query(Clients).filter(
        Clients.ClientCode == policy.ClientCode
    ).first()
    
    return {
        "status": "success",
        "policy": {
            "policy_number": policy.PolicyNumber,
            "premium": float(policy.Premium),
            "status": policy.Status,
            "start_date": policy.StartDate.isoformat() if policy.StartDate else None
        },
        "client": {
            "client_code": client.ClientCode,
            "first_name": client.FirstName,
            "last_name": client.LastName,
            "phone_number": client.PhoneNumber
        }
    }

@router.get("/balance/{policy_number}", response_model=BalanceResponse)
async def check_balance(
    policy_number: str,
    db: Session = Depends(get_db)
):
    policy = db.query(Policies).filter(
        Policies.PolicyNumber == policy_number
    ).first()
    
    if not policy:
        return {
            "status": "error",
            "message": "Policy not found"
        }
    
    return {
        "status": "success",
        "policy_number": policy.PolicyNumber,
        "premium": float(policy.Premium),
        "sum_assured": float(policy.SumAssured),
        "status": policy.Status
    }

@router.post("/beneficiary/add")
async def add_beneficiary(
    beneficiary: BeneficiaryCreate,
    db: Session = Depends(get_db)
):
    try:
        policy = db.query(Policies).filter(
            Policies.PolicyNumber == beneficiary.policy_number
        ).first()
        
        if not policy:
            return {
                "status": "error",
                "message": "Policy not found"
            }
        
        existing_beneficiaries = db.query(PoliciesDependant).filter(
            PoliciesDependant.ClientID == policy.ClientCode
        ).all()
        
        total_allocation = sum([50 for b in existing_beneficiaries])
        if total_allocation + beneficiary.percentage_allocation > 100:
            return {
                "status": "error",
                "message": "Total percentage allocation cannot exceed 100%"
            }
        
        if len(existing_beneficiaries) >= 6:
            return {
                "status": "error",
                "message": "Maximum number of beneficiaries (6) reached"
            }
        
        new_beneficiary = PoliciesDependant(
            ClientID=policy.ClientCode,
            full_name=beneficiary.full_name,
            date_of_birth=beneficiary.date_of_birth,
            relation_type="Beneficiary"
        )
        
        db.add(new_beneficiary)
        db.commit()
        
        return {
            "status": "success",
            "message": "Your request has been successfully submitted. You will receive an SMS on your status",
            "beneficiary": {
                "name": beneficiary.full_name,
                "date_of_birth": beneficiary.date_of_birth,
                "percentage_allocation": beneficiary.percentage_allocation
            }
        }
        
    except Exception as e:
        db.rollback()
        return {
            "status": "error",
            "message": f"Failed to add beneficiary: {str(e)}"
        }

@router.get("/beneficiary/{policy_number}")
async def get_beneficiaries(
    policy_number: str,
    db: Session = Depends(get_db)
):
    policy = db.query(Policies).filter(
        Policies.PolicyNumber == policy_number
    ).first()
    
    if not policy:
        return {
            "status": "error",
            "message": "Policy not found"
        }
    
    beneficiaries = db.query(PoliciesDependant).filter(
        PoliciesDependant.ClientID == policy.ClientCode
    ).all()
    
    return {
        "status": "success",
        "beneficiaries": [
            {
                "name": beneficiary.full_name,
                "date_of_birth": beneficiary.date_of_birth,
                "relation_type": beneficiary.relation_type
            }
            for beneficiary in beneficiaries
        ]
    }

@router.put("/beneficiary/update")
async def update_beneficiary(
    beneficiary: BeneficiaryUpdate,
    db: Session = Depends(get_db)
):
    """Update beneficiary information"""
    try:
        policy = db.query(Policies).filter(
            Policies.PolicyNumber == beneficiary.policy_number
        ).first()
        
        if not policy:
            return {
                "status": "error",
                "message": "Policy not found"
            }
        
        beneficiary_record = db.query(PoliciesDependant).filter(
            PoliciesDependant.ClientID == policy.ClientCode,
            PoliciesDependant.full_name == beneficiary.beneficiary_name
        ).first()
        
        if not beneficiary_record:
            return {
                "status": "error",
                "message": "Beneficiary not found"
            }
        
        if beneficiary.new_name:
            beneficiary_record.full_name = beneficiary.new_name
        
        db.commit()
        
        return {
            "status": "success",
            "message": "Your update request has been received successfully. You will receive SMS on the status of your request."
        }
        
    except Exception as e:
        db.rollback()
        return {
            "status": "error",
            "message": f"Failed to update beneficiary: {str(e)}"
        }

@router.post("/top-up")
async def policy_topup(
    topup: PolicyTopupRequest,
    db: Session = Depends(get_db)
):
    try:
        policy = db.query(Policies).filter(
            Policies.PolicyNumber == topup.policy_number
        ).first()
        
        if not policy:
            return {
                "status": "error",
                "message": "Policy not found"
            }
        
        payment = PaymentHistory(
            policy_id=policy.PolicyID,
            amount=topup.amount,
            payment_method="Mobile Money",
            status="completed",
            description="Policy top-up via USSD"
        )
        
        db.add(payment)
        db.commit()
        
        return {
            "status": "success",
            "message": "Payment successful. You will receive an SMS confirmation.",
            "amount": topup.amount,
            "policy_number": topup.policy_number
        }
        
    except Exception as e:
        db.rollback()
        return {
            "status": "error",
            "message": f"Payment failed: {str(e)}"
        }

@router.post("/referral")
async def referral_request(
    referral: ReferralRequest,
    db: Session = Depends(get_db)
):
    """Process referral request"""
    try:
        policy = db.query(Policies).filter(
            Policies.PolicyNumber == referral.referrer_policy_number
        ).first()
        
        if not policy:
            return {
                "status": "error",
                "message": "Policy not found"
            }
        
        referral_code = f"REF{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        return {
            "status": "success",
            "message": f"Referral code has been sent to {referral.friend_phone_number}",
            "referral_code": referral_code,
            "friend_number": referral.friend_phone_number
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Referral failed: {str(e)}"
        }

# @router.post("/dependent/add")
# async def add_dependent(
#     dependent: DependentCreate,
#     db: Session = Depends(get_db)
# ):
#     try:
#         policy = db.query(Policies).filter(
#             Policies.PolicyNumber == dependent.policy_number
#         ).first()
        
#         if not policy:
#             return {
#                 "status": "error",
#                 "message": "Policy not found"
#             }
        
#         new_dependent = PoliciesDependant(
#             ClientID=policy.ClientCode,
#             full_name=dependent.full_name,
#             date_of_birth=dependent.date_of_birth,
#             relation_type=dependent.relation_type
#         )
        
#         db.add(new_dependent)
#         db.commit()
        
#         return {
#             "status": "success",
#             "message": "Dependent added successfully",
#             "dependent": {
#                 "name": dependent.full_name,
#                 "date_of_birth": dependent.date_of_birth,
#                 "relation": dependent.relation_type
#             }
#         }
        
#     except Exception as e:
#         db.rollback()
#         return {
#             "status": "error",
#             "message": f"Failed to add dependent: {str(e)}"
#         }

@router.get("/referral/earnings/{policy_number}", response_model=ReferralEarningsResponse)
async def view_referral_earnings(
    policy_number: str,
    db: Session = Depends(get_db)
):
    """View referral earnings based on policy deductions and mandates"""
    policy = db.query(Policies).filter(
        Policies.PolicyNumber == policy_number
    ).first()
    
    if not policy:
        return {
            "status": "error",
            "message": "Policy not found"
        }
    
    total_points = 0
    pending_rewards = 0.0
    total_earned = 0.0
    
    mandate_records = db.query(Mandate).filter(
        Mandate.client_id == policy.ClientCode
    ).all()
    
    for mandate in mandate_records:
        if mandate.responseCode == "0000":
            total_points += 100
            pending_rewards += float(policy.Premium) * 0.10
    
    gov_deductions = db.query(GovernmentDeductionDB).filter(
        GovernmentDeductionDB.policy_id == policy_number
    ).all()
    
    for gov_deduction in gov_deductions:
        points_from_gov = int(gov_deduction.amount / 10)
        total_points += points_from_gov
        commission_from_gov = gov_deduction.amount * 0.05
        total_earned += commission_from_gov
        pending_rewards += commission_from_gov
    
    bank_deductions = db.query(BankDeductionDB).filter(
        BankDeductionDB.policy_id == policy.PolicyID
    ).all()
    
    for bank_deduction in bank_deductions:
        points_from_bank = int(float(policy.Premium) / 5)
        total_points += points_from_bank
        commission_from_bank = float(policy.Premium) * 0.08
        total_earned += commission_from_bank
        pending_rewards += commission_from_bank
    
    if policy.Status == 'Active':
        total_points += 50
    
    policy_age_months = 0
    if policy.StartDate:
        today = datetime.now().date()
        policy_age_months = (today.year - policy.StartDate.year) * 12 + (today.month - policy.StartDate.month)
        total_points += policy_age_months * 10
    
    if total_points == 0:
        total_points = 100
    
    if pending_rewards == 0:
        pending_rewards = float(policy.Premium) * 0.15
    
    if total_earned == 0:
        total_earned = float(policy.Premium) * 0.20
    
    return {
        "status": "success",
        "policy_number": policy_number,
        "policy_status": policy.Status,
        "premium": float(policy.Premium),
        "earnings_summary": {
            "points": total_points,
            "currency": "GHS",
            "pending_rewards": round(pending_rewards, 2),
            "total_earned": round(total_earned, 2),
            "available_for_withdrawal": round(pending_rewards * 0.8, 2)  
        },
        "breakdown": {
            "mandate_based_points": len(mandate_records) * 100,
            "government_deduction_earnings": len(gov_deductions),
            "bank_deduction_earnings": len(bank_deductions),
            "active_policy_bonus": 50 if policy.Status == 'Active' else 0,
            "policy_duration_bonus": policy_age_months * 10 if policy.StartDate else 0
        }
    }

@router.post("/referral/withdraw")
async def withdraw_rewards(
    withdraw: WithdrawRewardsRequest,
    db: Session = Depends(get_db)
):
    """Withdraw referral rewards"""
    try:
        policy = db.query(Policies).filter(
            Policies.PolicyNumber == withdraw.policy_number
        ).first()
        
        if not policy:
            return {
                "status": "error",
                "message": "Policy not found"
            }
        
        return {
            "status": "success",
            "message": "Your request has been received. You will receive your rewards within 48hrs.",
            "amount": withdraw.amount,
            "policy_number": withdraw.policy_number
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Withdrawal failed: {str(e)}"
        }


@router.post("/voluntary/payment")
async def voluntary_payment(
    payment: VoluntaryPaymentRequest,
    db: Session = Depends(get_db)
):
    """Process voluntary payment for policy"""
    try:
        policy = db.query(Policies).filter(
            Policies.PolicyNumber == payment.policy_number
        ).first()
        
        if not policy:
            return {
                "status": "error",
                "message": "Policy not found"
            }
        
        payment_record = PaymentHistory(
            policy_id=policy.PolicyID,
            amount=payment.amount,
            payment_method="Voluntary Payment",
            status="completed",
            description="Voluntary payment via USSD"
        )
        
        db.add(payment_record)
        db.commit()
        
        return {
            "status": "success",
            "message": "Payment successful. You will receive an SMS confirmation.",
            "amount": payment.amount,
            "policy_number": payment.policy_number
        }
        
    except Exception as e:
        db.rollback()
        return {
            "status": "error",
            "message": f"Payment failed: {str(e)}"
        }



@router.get("/contact-support", response_model=ContactSupportResponse)
async def contact_support():
    """Get contact support information"""
    return {
        "status": "success",
        "message": "Welcome to MyHealth. Get Customer Support.",
        "support_contact": "Contact support at the provided helpline"
    }

@router.post("/update-policy-plan")
async def update_policy_plan(
    update_request: UpdatePolicyPlanRequest,
    db: Session = Depends(get_db)
):
    """Update policy plan"""
    try:
        policy = db.query(Policies).filter(
            Policies.PolicyNumber == update_request.policy_number
        ).first()
        
        if not policy:
            return {
                "status": "error",
                "message": "Policy not found"
            }
        
        policy.Name = update_request.new_plan
        db.commit()
        
        return {
            "status": "success",
            "message": "Your request has been successfully submitted. You will receive an SMS on the status of your payment plan."
        }
        
    except Exception as e:
        db.rollback()
        return {
            "status": "error",
            "message": f"Policy plan update failed: {str(e)}"
        }

@router.post("/cancel-recurring")
async def cancel_recurring_payment(
    cancel_request: CancelRecurringRequest,
    db: Session = Depends(get_db)
):
    """Cancel recurring payment"""
    try:
        policy = db.query(Policies).filter(
            Policies.PolicyNumber == cancel_request.policy_number
        ).first()
        
        if not policy:
            return {
                "status": "error",
                "message": "Policy not found"
            }
        
        return {
            "status": "success",
            "message": "Your request is being processed. You will receive an SMS on the status."
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Cancellation failed: {str(e)}"
        }

@router.post("/enter-referral-code")
async def enter_referral_code(
    policy_number: str,
    referral_code: str,
    db: Session = Depends(get_db)
):
    """Enter referral code"""
    try:
        policy = db.query(Policies).filter(
            Policies.PolicyNumber == policy_number
        ).first()
        
        if not policy:
            return {
                "status": "error",
                "message": "Policy not found"
            }
        
        return {
            "status": "success",
            "message": "Thank you, the code has been recorded."
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Referral code entry failed: {str(e)}"
        }



# Main USSD Handler
# @router.post("/handler")
# async def ussd_handler(
#     session_id: str,
#     service_code: str,
#     phone_number: str,
#     text: str = "",
#     db: Session = Depends(get_db)
# ):

    
#     # Get or create session
#     session = get_ussd_session(session_id)
    
#     if text == "":
#         # Initial menu
#         response = """Welcome to Equity Health Insurance
# 1. Voluntary Payment
# 2. Buy Additional Insurance
# 3. Check Balance
# 4. Update Records
# 5. Reset/Forgot PIN
# 6. Referrals
# 7. Contact Support
# 8. Terms and Conditions"""
        
#         set_ussd_session(session_id, {"stage": "main_menu"})
#         return USSDResponse(response)
    
#     # Parse user input
#     inputs = text.split('*')
#     current_input = inputs[-1] if inputs else ""
    

#     stage = session.get('stage', 'main_menu')
    
#     if stage == "main_menu":
#         return handle_main_menu(session_id, current_input, phone_number, db)
#     elif stage == "buy_insurance":
#         return handle_buy_insurance(session_id, current_input, inputs, phone_number, db)
#     elif stage == "check_balance":
#         return handle_check_balance(session_id, current_input, phone_number, db)
#     elif stage == "update_records":
#         return handle_update_records(session_id, current_input, inputs, phone_number, db)
#     elif stage == "referrals":
#         return handle_referrals(session_id, current_input, inputs, phone_number, db)
    
#     return USSDResponse("Invalid option. Please try again.")

# def handle_main_menu(session_id: str, input: str, phone_number: str, db: Session):
#     """Handle main menu navigation"""
#     if input == "1":
#         # Voluntary Payment
#         set_ussd_session(session_id, {"stage": "voluntary_payment"})
#         return USSDResponse("Enter amount to contribute:")
    
#     elif input == "2":
#         # Buy Additional Insurance
#         set_ussd_session(session_id, {"stage": "buy_insurance", "step": "choose_product"})
#         response = """Choose your Policy
# 1. Micro Insurance (Monthly Policy)
# 2. Hide Top 50/Monthly
# 3. Back"""
#         return USSDResponse(response)
    
#     elif input == "3":
#         # Check Balance
#         set_ussd_session(session_id, {"stage": "check_balance"})
#         return USSDResponse("Enter your 4-digit PIN:")
    
#     elif input == "4":
#         # Update Records
#         set_ussd_session(session_id, {"stage": "update_records", "step": "main"})
#         response = """Select Option
# 1. Update Policy Plan
# 2. Cancel recurring payment
# 3. Add Beneficiary
# 0. Back"""
#         return USSDResponse(response)
    
#     elif input == "6":
#         # Referrals
#         set_ussd_session(session_id, {"stage": "referrals", "step": "main"})
#         response = """Select Option
# 1. Refer a Friend
# 2. Referral Earnings
# 3. Enter Referral Code
# 0. Back"""
#         return USSDResponse(response)
    
#     elif input == "8":
#         # Terms and Conditions
#         return USSDResponse("Full terms and conditions available at www.decision-insurance-policy", True)
    
#     else:
#         return USSDResponse("Invalid option. Please try again.")

# def handle_buy_insurance(session_id: str, input: str, inputs: List[str], phone_number: str, db: Session):
#     """Handle buy insurance flow"""
#     session = get_ussd_session(session_id)
#     step = session.get('step', 'choose_product')
    
#     if step == "choose_product":
#         if input == "1":
#             # Micro Insurance selected
#             session['product_type'] = 'micro'
#             session['step'] = 'choose_age_group'
#             set_ussd_session(session_id, session)
            
#             response = """Choose your age group
# 1. 0 years-59 years
# 2. 60 years -75 years
# 3. 75+
# 0. Back"""
#             return USSDResponse(response)
#         elif input == "0":
#             set_ussd_session(session_id, {"stage": "main_menu"})
#             return handle_main_menu(session_id, "", phone_number, db)
#         else:
#             return USSDResponse("Invalid option. Please try again.")
    
#     elif step == "choose_age_group":
#         if input in ["1", "2", "3"]:
#             session['age_group'] = input
#             session['step'] = 'confirm_contribution'
#             set_ussd_session(session_id, session)
            
#             response = "You will contribute GHS 8.50 monthly\n1. Confirm\n2. Back"
#             return USSDResponse(response)
#         elif input == "0":
#             session['step'] = 'choose_product'
#             set_ussd_session(session_id, session)
#             return handle_buy_insurance(session_id, "", inputs, phone_number, db)
#         else:
#             return USSDResponse("Invalid option. Please try again.")
    
#     elif step == "confirm_contribution":
#         if input == "1":
#             session['step'] = 'show_benefits'
#             set_ussd_session(session_id, session)
            
#             response = """Benefits
# 1. Primary care only
# 2. Medical consultations
# 3. Laboratory [Primary care]
# 4. Generic medications
# 5. Optical conditions and aids (GHC 300) - 1 year waiting period
# 6. Dental conditions and procedures
# 7. Monthly benefits
# 8. Benefits are not accrued
# 9. Maternity cover (2,000) - 1 year waiting period
# 1. Confirm
# 0. Back"""
#             return USSDResponse(response)
#         elif input == "2":
#             session['step'] = 'choose_age_group'
#             set_ussd_session(session_id, session)
#             return handle_buy_insurance(session_id, "", inputs, phone_number, db)
#         else:
#             return USSDResponse("Invalid option. Please try again.")
    
#     elif step == "show_benefits":
#         if input == "1":
#             session['step'] = 'enter_pin'
#             set_ussd_session(session_id, session)
#             return USSDResponse("Enter 4-digit PIN")
#         elif input == "0":
#             session['step'] = 'confirm_contribution'
#             set_ussd_session(session_id, session)
#             return handle_buy_insurance(session_id, "", inputs, phone_number, db)
#         else:
#             return USSDResponse("Invalid option. Please try again.")
    
#     elif step == "enter_pin":
#         if len(input) == 4:
#             # Process registration
#             session['step'] = 'registration_complete'
#             set_ussd_session(session_id, session)
            
#             return USSDResponse("Registration request received. Please authorize payment prompt. An SMS will be sent to you on the status of your registration.", True)
#         else:
#             return USSDResponse("Invalid PIN. Enter 4-digit PIN:")

# def handle_check_balance(session_id: str, input: str, phone_number: str, db: Session):
#     """Handle check balance flow"""
#     session = get_ussd_session(session_id)
    
#     if 'pin_entered' not in session:
#         if len(input) == 4:
#             # Validate PIN and get balance
#             session['pin_entered'] = True
#             set_ussd_session(session_id, session)
            
#             # Lookup client by phone number
#             client = db.query(Clients).filter(Clients.PhoneNumber == phone_number).first()
#             if client:
#                 policies = db.query(Policies).filter(Policies.ClientCode == client.ClientCode).all()
#                 if policies:
#                     premium = float(policies[0].Premium)
#                     return USSDResponse(f"Your Premium Is GHS{premium:.2f}.", True)
            
#             return USSDResponse("No active policy found.", True)
#         else:
#             return USSDResponse("Invalid PIN. Enter 4-digit PIN:")
    
#     return USSDResponse("Session completed.", True)

# def handle_update_records(session_id: str, input: str, inputs: List[str], phone_number: str, db: Session):
#     """Handle update records flow"""
#     session = get_ussd_session(session_id)
#     step = session.get('step', 'main')
    
#     if step == "main":
#         if input == "1":
#             # Update Policy Plan
#             session['step'] = 'update_policy_plan'
#             set_ussd_session(session_id, session)
            
#             response = "You are currently on the Micro Insurance Policy Plan of GHC95.00 Monthly. Would you like to proceed to make changes?\n1. Yes\n2. Cancel"
#             return USSDResponse(response)
        
#         elif input == "2":
#             # Cancel recurring payment
#             session['step'] = 'cancel_recurring'
#             set_ussd_session(session_id, session)
            
#             response = "You want to cancel your recurring contribution of GHC95.00 Monthly?\n1. Yes\n2. No"
#             return USSDResponse(response)
        
#         elif input == "3":
#             # Add Beneficiary
#             session['step'] = 'add_beneficiary'
#             session['beneficiary_step'] = 'enter_name'
#             set_ussd_session(session_id, session)
            
#             return USSDResponse("Enter Beneficiary's Name or 0 to go back")
        
#         elif input == "0":
#             set_ussd_session(session_id, {"stage": "main_menu"})
#             return handle_main_menu(session_id, "", phone_number, db)
        
#         else:
#             return USSDResponse("Invalid option. Please try again.")
    
#     elif step == "update_policy_plan":
#         if input == "1":
#             session['step'] = 'policy_plan_confirm'
#             set_ussd_session(session_id, session)
            
#             response = "The new policy plan will only take effect after the end of the current policy year. Would you like to proceed?\n1. Yes\n2. Cancel"
#             return USSDResponse(response)
#         elif input == "2":
#             set_ussd_session(session_id, {"stage": "main_menu"})
#             return handle_main_menu(session_id, "", phone_number, db)
#         else:
#             return USSDResponse("Invalid option. Please try again.")
    
#     elif step == "policy_plan_confirm":
#         if input == "1":
#             # Process policy plan update
#             return USSDResponse("Your request has been successfully submitted. You will receive an SMS on the status of your payment plan.", True)
#         else:
#             session['step'] = 'update_policy_plan'
#             set_ussd_session(session_id, session)
#             return handle_update_records(session_id, "", inputs, phone_number, db)
    
#     elif step == "cancel_recurring":
#         if input == "1":
#             session['step'] = 'cancel_recurring_pin'
#             set_ussd_session(session_id, session)
#             return USSDResponse("Enter 4 digit PIN")
#         elif input == "2":
#             set_ussd_session(session_id, {"stage": "main_menu"})
#             return handle_main_menu(session_id, "", phone_number, db)
#         else:
#             return USSDResponse("Invalid option. Please try again.")
    
#     elif step == "cancel_recurring_pin":
#         if len(input) == 4:
#             # Process cancellation
#             return USSDResponse("Your request is being processed. You will receive an SMS on the status.", True)
#         else:
#             return USSDResponse("Invalid PIN. Enter 4-digit PIN:")
    
#     elif step == "add_beneficiary":
#         beneficiary_step = session.get('beneficiary_step', 'enter_name')
        
#         if beneficiary_step == "enter_name":
#             if input == "0":
#                 set_ussd_session(session_id, {"stage": "update_records", "step": "main"})
#                 return handle_update_records(session_id, "", inputs, phone_number, db)
#             else:
#                 session['beneficiary_name'] = input
#                 session['beneficiary_step'] = 'enter_dob'
#                 set_ussd_session(session_id, session)
#                 return USSDResponse("Enter Beneficiary's DOB eg DDMMYYYY")
        
#         elif beneficiary_step == "enter_dob":
#             if input == "0":
#                 session['beneficiary_step'] = 'enter_name'
#                 set_ussd_session(session_id, session)
#                 return handle_update_records(session_id, "", inputs, phone_number, db)
#             else:
#                 session['beneficiary_dob'] = input
#                 session['beneficiary_step'] = 'enter_phone'
#                 set_ussd_session(session_id, session)
#                 return USSDResponse("Enter Beneficiary's Phone Number or 0 to go back")
        
#         elif beneficiary_step == "enter_phone":
#             if input == "0":
#                 session['beneficiary_step'] = 'enter_dob'
#                 set_ussd_session(session_id, session)
#                 return handle_update_records(session_id, "", inputs, phone_number, db)
#             else:
#                 session['beneficiary_phone'] = input
#                 session['beneficiary_step'] = 'enter_allocation'
#                 set_ussd_session(session_id, session)
#                 return USSDResponse("Enter Percentage Allocation. Total percentage is 100%")
        
#         elif beneficiary_step == "enter_allocation":
#             if input == "0":
#                 session['beneficiary_step'] = 'enter_phone'
#                 set_ussd_session(session_id, session)
#                 return handle_update_records(session_id, "", inputs, phone_number, db)
#             else:
#                 try:
#                     allocation = float(input)
#                     session['beneficiary_allocation'] = allocation
#                     session['beneficiary_step'] = 'confirm_details'
#                     set_ussd_session(session_id, session)
                    
#                     name = session.get('beneficiary_name', '')
#                     dob = session.get('beneficiary_dob', '')
#                     phone = session.get('beneficiary_phone', '')
                    
#                     response = f"Confirm details of Beneficiary\nName: {name}\nDOB: {dob}\nPhone number: {phone}\n1. Confirm\n0. Back"
#                     return USSDResponse(response)
#                 except ValueError:
#                     return USSDResponse("Invalid percentage. Enter Percentage Allocation:")
        
#         elif beneficiary_step == "confirm_details":
#             if input == "1":
#                 session['beneficiary_step'] = 'confirm_allocation'
#                 set_ussd_session(session_id, session)
                
#                 allocation = session.get('beneficiary_allocation', 50)
#                 response = f"Would you like to allocate {allocation}% to {session.get('beneficiary_name', '')}?\n1. Yes\n0. Back"
#                 return USSDResponse(response)
#             elif input == "0":
#                 session['beneficiary_step'] = 'enter_allocation'
#                 set_ussd_session(session_id, session)
#                 return handle_update_records(session_id, "", inputs, phone_number, db)
#             else:
#                 return USSDResponse("Invalid option. Please try again.")
        
#         elif beneficiary_step == "confirm_allocation":
#             if input == "1":
#                 session['beneficiary_step'] = 'enter_pin'
#                 set_ussd_session(session_id, session)
#                 return USSDResponse("Enter 4 digit PIN")
#             elif input == "0":
#                 session['beneficiary_step'] = 'confirm_details'
#                 set_ussd_session(session_id, session)
#                 return handle_update_records(session_id, "", inputs, phone_number, db)
#             else:
#                 return USSDResponse("Invalid option. Please try again.")
        
#         elif beneficiary_step == "enter_pin":
#             if len(input) == 4:
#                 # Process beneficiary addition
#                 return USSDResponse("Your request has been successfully submitted. You will receive an SMS on your status", True)
#             else:
#                 return USSDResponse("Invalid PIN. Enter 4-digit PIN:")
    
#     return USSDResponse("Session completed.", True)

# def handle_referrals(session_id: str, input: str, inputs: List[str], phone_number: str, db: Session):
#     """Handle referrals flow"""
#     session = get_ussd_session(session_id)
#     step = session.get('step', 'main')
    
#     if step == "main":
#         if input == "1":
#             # Refer a Friend
#             session['step'] = 'refer_friend'
#             set_ussd_session(session_id, session)
#             return USSDResponse("Enter friend's number")
        
#         elif input == "2":
#             # Referral Earnings
#             session['step'] = 'referral_earnings'
#             set_ussd_session(session_id, session)
            
#             response = """Select Option
# 1. Check earnings
# 2. Withdraw Rewards
# 3. Back"""
#             return USSDResponse(response)
        
#         elif input == "3":
#             # Enter Referral Code
#             session['step'] = 'enter_referral_code'
#             set_ussd_session(session_id, session)
#             return USSDResponse("Enter Referral Code")
        
#         elif input == "0":
#             set_ussd_session(session_id, {"stage": "main_menu"})
#             return handle_main_menu(session_id, "", phone_number, db)
        
#         else:
#             return USSDResponse("Invalid option. Please try again.")
    
#     elif step == "refer_friend":
#         if input and len(input) >= 10:  # Basic phone number validation
#             # Process referral
#             return USSDResponse(f"Referral code has been sent to {input}.", True)
#         else:
#             return USSDResponse("Invalid phone number. Enter friend's number:")
    
#     elif step == "referral_earnings":
#         if input == "1":
#             # Check earnings
#             return USSDResponse("You have earned 1000 points", True)
        
#         elif input == "2":
#             # Withdraw Rewards
#             session['step'] = 'withdraw_rewards'
#             set_ussd_session(session_id, session)
#             return USSDResponse("Enter amount to withdraw or 0 to go back")
        
#         elif input == "3":
#             session['step'] = 'main'
#             set_ussd_session(session_id, session)
#             return handle_referrals(session_id, "", inputs, phone_number, db)
        
#         else:
#             return USSDResponse("Invalid option. Please try again.")
    
#     elif step == "withdraw_rewards":
#         if input == "0":
#             session['step'] = 'referral_earnings'
#             set_ussd_session(session_id, session)
#             return handle_referrals(session_id, "", inputs, phone_number, db)
#         else:
#             try:
#                 amount = float(input)
#                 return USSDResponse("Your request has been received. You will receive your rewards within 48hrs", True)
#             except ValueError:
#                 return USSDResponse("Invalid amount. Enter amount to withdraw:")
    
#     elif step == "enter_referral_code":
#         if input and len(input) >= 3:  # Basic referral code validation
#             return USSDResponse("Thank you, the code has been recorded.", True)
#         else:
#             return USSDResponse("Invalid referral code. Enter Referral Code:")
    
#     return USSDResponse("Session completed.", True)

# def handle_voluntary_payment(session_id: str, input: str, phone_number: str, db: Session):
#     """Handle voluntary payment flow"""
#     session = get_ussd_session(session_id)
    
#     if 'amount_entered' not in session:
#         try:
#             amount = float(input)
#             session['amount'] = amount
#             session['amount_entered'] = True
#             set_ussd_session(session_id, session)
            
#             # Lookup client policies
#             client = db.query(Clients).filter(Clients.PhoneNumber == phone_number).first()
#             if client:
#                 policies = db.query(Policies).filter(Policies.ClientCode == client.ClientCode).all()
#                 if policies:
#                     response = f"Confirm payment of GHS {amount:.2f} for policy {policies[0].PolicyNumber}?\n1. Confirm\n2. Cancel"
#                     return USSDResponse(response)
            
#             return USSDResponse("No active policy found. Please contact support.", True)
#         except ValueError:
#             return USSDResponse("Invalid amount. Enter amount to contribute:")
    
#     else:
#         if input == "1":
#             # Process payment
#             amount = session.get('amount', 0)
#             return USSDResponse(f"Payment of GHS {amount:.2f} processed successfully. You will receive an SMS confirmation.", True)
#         elif input == "2":
#             return USSDResponse("Payment cancelled.", True)
#         else:
#             return USSDResponse("Invalid option. Please try again.")

# Health check
@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "USSD API"}