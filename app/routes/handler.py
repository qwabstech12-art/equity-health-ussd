from app.routes.ussd import *


router = APIRouter(prefix="/ussd")


@router.post("/handler")
async def ussd_handler(
    session_id: str,
    service_code: str,
    phone_number: str,
    text: str = "",
    db: Session = Depends(get_db)
):
    
    session = get_ussd_session(session_id)
    
    if text == "":
        
        response = """Welcome to Equity Health Insurance
1. Voluntary Payment
2. Buy Insurance
3. Check Balance
4. Update Records
5. Reset/Forgot PIN
6. Referrals
7. Contact Support
8. Terms and Conditions"""
        
        set_ussd_session(session_id, {"stage": "main_menu"})
        return USSDResponse(response)
    
    # Parse user input
    inputs = text.split('*')
    current_input = inputs[-1] if inputs else ""
    
    stage = session.get('stage', 'main_menu')
    
    if stage == "main_menu":
        return handle_main_menu(session_id, current_input, phone_number, db)
    elif stage == "buy_insurance":
        return handle_buy_insurance(session_id, current_input, inputs, phone_number, db)
    elif stage == "check_balance":
        return handle_check_balance(session_id, current_input, phone_number, db)
    elif stage == "update_records":
        return handle_update_records(session_id, current_input, inputs, phone_number, db)
    elif stage == "referrals":
        return handle_referrals(session_id, current_input, inputs, phone_number, db)
    elif stage == "voluntary_payment":
        return handle_voluntary_payment(session_id, current_input, phone_number, db)
    elif stage == "reset_pin":
        return handle_reset_pin(session_id, current_input, inputs, phone_number, db)
    
    return USSDResponse("Invalid option. Please try again.")

def handle_main_menu(session_id: str, input: str, phone_number: str, db: Session):
    """Handle main menu navigation"""
    if input == "1":
        # Voluntary Payment
        set_ussd_session(session_id, {"stage": "voluntary_payment"})
        return USSDResponse("Enter amount to contribute:")
    
    elif input == "2":
        # Buy Insurance
        set_ussd_session(session_id, {"stage": "buy_insurance", "step": "check_existing_client"})
        return USSDResponse("Do you have an existing account?\n1. Yes\n2. No\n0. Back")
    
    elif input == "3":
        # Check Balance
        set_ussd_session(session_id, {"stage": "check_balance"})
        return USSDResponse("Enter your 4-digit PIN:")
    
    elif input == "4":
        # Update Records
        set_ussd_session(session_id, {"stage": "update_records", "step": "main"})
        response = """Select Option
1. Update Policy Plan
2. Cancel recurring payment
3. Add Beneficiary
0. Back"""
        return USSDResponse(response)
    
    elif input == "5":
        # Reset/Forgot PIN
        set_ussd_session(session_id, {"stage": "reset_pin", "step": "main"})
        response = """Reset/Forgot PIN
1. Reset PIN
2. Forgot PIN
0. Back"""
        return USSDResponse(response)
    
    elif input == "6":
        # Referrals
        set_ussd_session(session_id, {"stage": "referrals", "step": "main"})
        response = """Select Option
1. Refer a Friend
2. Referral Earnings
3. Enter Referral Code
0. Back"""
        return USSDResponse(response)
    
    elif input == "7":
        # Contact Support
        return USSDResponse("Contact Support:\nCall: 0302-XXXXXX\nEmail: support@equityhealth.com", True)
    
    elif input == "8":
        # Terms and Conditions
        return USSDResponse("Full terms and conditions available at www.decision-insurance-policy", True)
    
    else:
        return USSDResponse("Invalid option. Please try again.")

async def handle_buy_insurance(session_id: str, input: str, inputs: List[str], phone_number: str, db: Session):
    """Handle buy insurance flow with new registration process"""
    session = get_ussd_session(session_id)
    step = session.get('step', 'check_existing_client')
    
    if step == "check_existing_client":
        if input == "1":
            # Existing client - verify PIN
            session['step'] = 'verify_pin'
            set_ussd_session(session_id, session)
            return USSDResponse("Enter your 4-digit PIN:")
        
        elif input == "2":
            # New client - start registration
            session['step'] = 'choose_registration_type'
            set_ussd_session(session_id, session)
            response = """Choose registration type:
1. Self Registration
2. Agent Assisted Registration
0. Back"""
            return USSDResponse(response)
        
        elif input == "0":
            set_ussd_session(session_id, {"stage": "main_menu"})
            return handle_main_menu(session_id, "", phone_number, db)
        
        else:
            return USSDResponse("Invalid option. Please try again.")
    
    elif step == "verify_pin":
        if len(input) == 4:
            # Verify PIN for existing client
            client = db.query(Clients).filter(Clients.PhoneNumber == phone_number).first()
            if client:
                pin_record = db.query(ClientPIN).filter(ClientPIN.client_code == client.ClientCode).first()
                if pin_record and verify_pin(pin_record.pin_hash, input):
                    session['client_code'] = client.ClientCode
                    session['step'] = 'choose_product'
                    set_ussd_session(session_id, session)
                    response = """Choose Insurance Product:
1. Micro Insurance
2. Telemedicine Insurance
3. NHIS Top-Up Scheme
4. Ayaresabea Banbo Sika (ABS)
5. Daakye Apomuden
6. Ebusua Health
0. Back"""
                    return USSDResponse(response)
                else:
                    return USSDResponse("Invalid PIN. Please try again or select 'Forgot PIN' from main menu.")
            else:
                return USSDResponse("Client not found. Please register first.")
        else:
            return USSDResponse("Invalid PIN. Enter 4-digit PIN:")
    
    elif step == "choose_registration_type":
        if input == "1":
            # Self registration
            session['agent_code'] = "EHI_0000_C"
            session['step'] = 'create_pin'
            set_ussd_session(session_id, session)
            return USSDResponse("Create your 4-digit PIN:")
        
        elif input == "2":
            # Agent assisted registration
            session['step'] = 'enter_agent_code'
            set_ussd_session(session_id, session)
            return USSDResponse("Enter Agent Code:")
        
        elif input == "0":
            session['step'] = 'check_existing_client'
            set_ussd_session(session_id, session)
            return handle_buy_insurance(session_id, "", inputs, phone_number, db)
        
        else:
            return USSDResponse("Invalid option. Please try again.")
    
    elif step == "enter_agent_code":
        if input and len(input) >= 3:
            # Validate agent code
            agent_validation = await validate_agent_code(input, db)
            if agent_validation["is_valid"]:
                session['agent_code'] = input
                session['step'] = 'create_pin'
                set_ussd_session(session_id, session)
                return USSDResponse("Create your 4-digit PIN:")
            else:
                return USSDResponse("Invalid agent code. Please enter valid agent code:")
        else:
            return USSDResponse("Invalid agent code. Enter Agent Code:")
    
    elif step == "create_pin":
        if len(input) == 4 and input.isdigit():
            session['pin'] = input
            session['step'] = 'confirm_pin'
            set_ussd_session(session_id, session)
            return USSDResponse("Confirm your 4-digit PIN:")
        else:
            return USSDResponse("PIN must be 4 digits. Create your 4-digit PIN:")
    
    elif step == "confirm_pin":
        if input == session.get('pin'):
            # PIN confirmed, create client
            try:
                # Create new client
                new_client = Clients(
                    ClientCode=f"CLI{phone_number}{datetime.now().strftime('%H%M%S')}",
                    AgentID=session.get('agent_id'),
                    PhoneNumber=phone_number,
                    FirstName="",
                    LastName="", 
                    Gender='Other',
                    Status='Active',
                    CreatedAt=datetime.now()
                )
                
                db.add(new_client)
                db.flush()
                
                # Create PIN
                new_pin = ClientPIN(
                    client_code=new_client.ClientCode,
                    pin_hash=hash_pin(input),
                    is_active=True
                )
                
                db.add(new_pin)
                db.commit()
                
                session['client_code'] = new_client.ClientCode
                session['step'] = 'choose_product'
                set_ussd_session(session_id, session)
                
                response = """Registration successful! Choose Insurance Product:
1. Micro Insurance
2. Telemedicine Insurance
3. NHIS Top-Up Scheme
4. Ayaresabea Banbo Sika (ABS)
5. Daakye Apomuden
6. Ebusua Health
0. Back"""
                return USSDResponse(response)
                
            except Exception as e:
                db.rollback()
                return USSDResponse("Registration failed. Please try again.", True)
        else:
            return USSDResponse("PINs do not match. Create your 4-digit PIN:")
    
    elif step == "choose_product":
        product_map = {
            "1": "Micro Product",
            "2": "Telemedicine Insurance", 
            "3": "NHIS Top-Up Scheme",
            "4": "Ayaresabea Banbo Sika (ABS)",
            "5": "Daakye Apomuden",
            "6": "Ebusua Health"
        }
        
        if input in product_map:
            session['product_name'] = product_map[input]
            session['step'] = 'choose_age_group'
            set_ussd_session(session_id, session)
            
            response = """Choose your age group:
1. 0-59 years
2. 60-75 years  
3. 75+ years
0. Back"""
            return USSDResponse(response)
        elif input == "0":
            set_ussd_session(session_id, {"stage": "main_menu"})
            return handle_main_menu(session_id, "", phone_number, db)
        else:
            return USSDResponse("Invalid option. Please try again.")
    
    elif step == "choose_age_group":
        age_group_map = {
            "1": "0-59",
            "2": "60-75", 
            "3": "75+"
        }
        
        if input in age_group_map:
            session['age_group'] = age_group_map[input]
            session['step'] = 'show_premium'
            set_ussd_session(session_id, session)
            
            # Get premium amount based on product and age group
            premium = await get_premium_amount(session['product_name'], session['age_group'])
            session['premium'] = premium
            
            return USSDResponse(f"Premium: GHS {premium:.2f} monthly\n1. Confirm\n2. Back")
        elif input == "0":
            session['step'] = 'choose_product'
            set_ussd_session(session_id, session)
            return handle_buy_insurance(session_id, "", inputs, phone_number, db)
        else:
            return USSDResponse("Invalid option. Please try again.")
    
    elif step == "show_premium":
        if input == "1":
            # Create policy
            try:
                policy_result = await create_policy(
                    session['client_code'],
                    session['product_name'], 
                    session['age_group'],
                    db
                )
                
                if policy_result["status"] == "success":
                    return USSDResponse(f"Policy created successfully! Policy Number: {policy_result['policy_number']}. Premium: GHS {policy_result['premium']:.2f}/month", True)
                else:
                    return USSDResponse(f"Policy creation failed: {policy_result['message']}", True)
                    
            except Exception as e:
                return USSDResponse("Policy creation failed. Please try again.", True)
        
        elif input == "2":
            session['step'] = 'choose_age_group'
            set_ussd_session(session_id, session)
            return handle_buy_insurance(session_id, "", inputs, phone_number, db)
        else:
            return USSDResponse("Invalid option. Please try again.")
    
    return USSDResponse("Session completed.", True)

async def get_premium_amount(product_name: str, age_group: str) -> float:
    """Get premium amount based on product and age group"""
    # Default premiums - in real implementation, fetch from product details
    premium_map = {
        "Micro Product": 95.00,
        "Telemedicine Insurance": 60.00,
        "NHIS Top-Up Scheme": 60.00,
        "Ayaresabea Banbo Sika (ABS)": 23.00,
        "Daakye Apomuden": 60.00,
        "Ebusua Health": 3950.50
    }
    
    return premium_map.get(product_name, 50.00)

def handle_check_balance(session_id: str, input: str, phone_number: str, db: Session):
    """Handle check balance flow with PIN verification"""
    session = get_ussd_session(session_id)
    
    if 'pin_entered' not in session:
        if len(input) == 4:
            # Verify PIN first
            client = db.query(Clients).filter(Clients.PhoneNumber == phone_number).first()
            if client:
                pin_record = db.query(ClientPIN).filter(ClientPIN.client_code == client.ClientCode).first()
                if pin_record and verify_pin(pin_record.pin_hash, input):
                    session['pin_entered'] = True
                    set_ussd_session(session_id, session)
                    
                    # Get balance
                    policies = db.query(Policies).filter(
                        Policies.ClientCode == client.ClientCode,
                        Policies.Status == 'Active'
                    ).all()
                    
                    if policies:
                        total_premium = sum(float(policy.Premium) for policy in policies)
                        active_policies = len(policies)
                        return USSDResponse(f"Active Policies: {active_policies}\nTotal Monthly Premium: GHS {total_premium:.2f}", True)
                    else:
                        return USSDResponse("No active policies found.", True)
                else:
                    return USSDResponse("Invalid PIN. Please try again.", True)
            else:
                return USSDResponse("Client not found. Please register first.", True)
        else:
            return USSDResponse("Invalid PIN. Enter 4-digit PIN:")
    
    return USSDResponse("Session completed.", True)

def handle_reset_pin(session_id: str, input: str, inputs: List[str], phone_number: str, db: Session):
    """Handle reset/forgot PIN flow"""
    session = get_ussd_session(session_id)
    step = session.get('step', 'main')
    
    if step == "main":
        if input == "1":
            # Reset PIN
            session['step'] = 'reset_current_pin'
            set_ussd_session(session_id, session)
            return USSDResponse("Enter current 4-digit PIN:")
        
        elif input == "2":
            # Forgot PIN
            session['step'] = 'forgot_pin_verify'
            set_ussd_session(session_id, session)
            return USSDResponse("Enter your phone number to verify:")
        
        elif input == "0":
            set_ussd_session(session_id, {"stage": "main_menu"})
            return handle_main_menu(session_id, "", phone_number, db)
        
        else:
            return USSDResponse("Invalid option. Please try again.")
    
    elif step == "reset_current_pin":
        if len(input) == 4:
            client = db.query(Clients).filter(Clients.PhoneNumber == phone_number).first()
            if client:
                pin_record = db.query(ClientPIN).filter(ClientPIN.client_code == client.ClientCode).first()
                if pin_record and verify_pin(pin_record.pin_hash, input):
                    session['step'] = 'reset_new_pin'
                    set_ussd_session(session_id, session)
                    return USSDResponse("Enter new 4-digit PIN:")
                else:
                    return USSDResponse("Invalid current PIN. Please try again.")
            else:
                return USSDResponse("Client not found.", True)
        else:
            return USSDResponse("Invalid PIN. Enter 4-digit PIN:")
    
    elif step == "reset_new_pin":
        if len(input) == 4 and input.isdigit():
            session['new_pin'] = input
            session['step'] = 'reset_confirm_pin'
            set_ussd_session(session_id, session)
            return USSDResponse("Confirm new 4-digit PIN:")
        else:
            return USSDResponse("PIN must be 4 digits. Enter new 4-digit PIN:")
    
    elif step == "reset_confirm_pin":
        if input == session.get('new_pin'):
            # Update PIN
            client = db.query(Clients).filter(Clients.PhoneNumber == phone_number).first()
            if client:
                pin_record = db.query(ClientPIN).filter(ClientPIN.client_code == client.ClientCode).first()
                if pin_record:
                    pin_record.pin_hash = hash_pin(input)
                    pin_record.failed_attempts = 0
                    pin_record.updated_at = datetime.utcnow()
                    db.commit()
                    return USSDResponse("PIN reset successfully!", True)
            return USSDResponse("Error resetting PIN.", True)
        else:
            return USSDResponse("PINs do not match. Enter new 4-digit PIN:")
    
    elif step == "forgot_pin_verify":
        # Verify phone number matches
        if input == phone_number:
            session['step'] = 'forgot_new_pin'
            set_ussd_session(session_id, session)
            return USSDResponse("Create new 4-digit PIN:")
        else:
            return USSDResponse("Phone number does not match. Enter your registered phone number:")
    
    elif step == "forgot_new_pin":
        if len(input) == 4 and input.isdigit():
            session['new_pin'] = input
            session['step'] = 'forgot_confirm_pin'
            set_ussd_session(session_id, session)
            return USSDResponse("Confirm new 4-digit PIN:")
        else:
            return USSDResponse("PIN must be 4 digits. Create new 4-digit PIN:")
    
    elif step == "forgot_confirm_pin":
        if input == session.get('new_pin'):
            # Update PIN
            client = db.query(Clients).filter(Clients.PhoneNumber == phone_number).first()
            if client:
                pin_record = db.query(ClientPIN).filter(ClientPIN.client_code == client.ClientCode).first()
                if pin_record:
                    pin_record.pin_hash = hash_pin(input)
                    pin_record.failed_attempts = 0
                    pin_record.is_active = True
                    pin_record.updated_at = datetime.utcnow()
                    db.commit()
                    return USSDResponse("PIN reset successfully! Temporary PIN sent via SMS.", True)
            return USSDResponse("Error resetting PIN.", True)
        else:
            return USSDResponse("PINs do not match. Create new 4-digit PIN:")
    
    return USSDResponse("Session completed.", True)

def handle_referrals(session_id: str, input: str, inputs: List[str], phone_number: str, db: Session):
    session = get_ussd_session(session_id)
    step = session.get('step', 'main')
    
    if step == "main":
        if input == "1":
            # Refer a Friend
            session['step'] = 'refer_friend'
            set_ussd_session(session_id, session)
            return USSDResponse("Enter friend's number")
        
        elif input == "2":
            # Referral Earnings
            session['step'] = 'referral_earnings'
            set_ussd_session(session_id, session)
            
            response = """Select Option
1. Check earnings
2. Withdraw Rewards
3. Back"""
            return USSDResponse(response)
        
        elif input == "3":
            # Enter Referral Code
            session['step'] = 'enter_referral_code'
            set_ussd_session(session_id, session)
            return USSDResponse("Enter Referral Code")
        
        elif input == "0":
            set_ussd_session(session_id, {"stage": "main_menu"})
            return handle_main_menu(session_id, "", phone_number, db)
        
        else:
            return USSDResponse("Invalid option. Please try again.")
    
    elif step == "refer_friend":
        if input and len(input) >= 10:  # Basic phone number validation
            # Process referral
            return USSDResponse(f"Referral code has been sent to {input}.", True)
        else:
            return USSDResponse("Invalid phone number. Enter friend's number:")
    
    elif step == "referral_earnings":
        if input == "1":
            # Check earnings
            return USSDResponse("You have earned 1000 points", True)
        
        elif input == "2":
            # Withdraw Rewards
            session['step'] = 'withdraw_rewards'
            set_ussd_session(session_id, session)
            return USSDResponse("Enter amount to withdraw or 0 to go back")
        
        elif input == "3":
            session['step'] = 'main'
            set_ussd_session(session_id, session)
            return handle_referrals(session_id, "", inputs, phone_number, db)
        
        else:
            return USSDResponse("Invalid option. Please try again.")
    
    elif step == "withdraw_rewards":
        if input == "0":
            session['step'] = 'referral_earnings'
            set_ussd_session(session_id, session)
            return handle_referrals(session_id, "", inputs, phone_number, db)
        else:
            try:
                amount = float(input)
                return USSDResponse("Your request has been received. You will receive your rewards within 48hrs", True)
            except ValueError:
                return USSDResponse("Invalid amount. Enter amount to withdraw:")
    
    elif step == "enter_referral_code":
        if input and len(input) >= 3:  # Basic referral code validation
            return USSDResponse("Thank you, the code has been recorded.", True)
        else:
            return USSDResponse("Invalid referral code. Enter Referral Code:")
    
    return USSDResponse("Session completed.", True)

def handle_voluntary_payment(session_id: str, input: str, phone_number: str, db: Session):
    """Handle voluntary payment flow"""
    session = get_ussd_session(session_id)
    
    if 'amount_entered' not in session:
        try:
            amount = float(input)
            session['amount'] = amount
            session['amount_entered'] = True
            set_ussd_session(session_id, session)
            
            # Lookup client policies
            client = db.query(Clients).filter(Clients.PhoneNumber == phone_number).first()
            if client:
                policies = db.query(Policies).filter(Policies.ClientCode == client.ClientCode).all()
                if policies:
                    response = f"Confirm payment of GHS {amount:.2f} for policy {policies[0].PolicyNumber}?\n1. Confirm\n2. Cancel"
                    return USSDResponse(response)
            
            return USSDResponse("No active policy found. Please contact support.", True)
        except ValueError:
            return USSDResponse("Invalid amount. Enter amount to contribute:")
    
    else:
        if input == "1":
            # Process payment
            amount = session.get('amount', 0)
            return USSDResponse(f"Payment of GHS {amount:.2f} processed successfully. You will receive an SMS confirmation.", True)
        elif input == "2":
            return USSDResponse("Payment cancelled.", True)
        else:
            return USSDResponse("Invalid option. Please try again.")
        
        
def handle_update_records(session_id: str, input: str, inputs: List[str], phone_number: str, db: Session):
    session = get_ussd_session(session_id)
    step = session.get('step', 'main')
    
    if step == "main":
        if input == "1":
            # Update Policy Plan
            session['step'] = 'update_policy_plan'
            set_ussd_session(session_id, session)
            
            response = "You are currently on the Micro Insurance Policy Plan of GHC95.00 Monthly. Would you like to proceed to make changes?\n1. Yes\n2. Cancel"
            return USSDResponse(response)
        
        elif input == "2":
            # Cancel recurring payment
            session['step'] = 'cancel_recurring'
            set_ussd_session(session_id, session)
            
            response = "You want to cancel your recurring contribution of GHC95.00 Monthly?\n1. Yes\n2. No"
            return USSDResponse(response)
        
        elif input == "3":
            # Add Beneficiary
            session['step'] = 'add_beneficiary'
            session['beneficiary_step'] = 'enter_name'
            set_ussd_session(session_id, session)
            
            return USSDResponse("Enter Beneficiary's Name or 0 to go back")
        
        elif input == "0":
            set_ussd_session(session_id, {"stage": "main_menu"})
            return handle_main_menu(session_id, "", phone_number, db)
        
        else:
            return USSDResponse("Invalid option. Please try again.")
    
    elif step == "update_policy_plan":
        if input == "1":
            session['step'] = 'policy_plan_confirm'
            set_ussd_session(session_id, session)
            
            response = "The new policy plan will only take effect after the end of the current policy year. Would you like to proceed?\n1. Yes\n2. Cancel"
            return USSDResponse(response)
        elif input == "2":
            set_ussd_session(session_id, {"stage": "main_menu"})
            return handle_main_menu(session_id, "", phone_number, db)
        else:
            return USSDResponse("Invalid option. Please try again.")
    
    elif step == "policy_plan_confirm":
        if input == "1":
            # Process policy plan update
            return USSDResponse("Your request has been successfully submitted. You will receive an SMS on the status of your payment plan.", True)
        else:
            session['step'] = 'update_policy_plan'
            set_ussd_session(session_id, session)
            return handle_update_records(session_id, "", inputs, phone_number, db)
    
    elif step == "cancel_recurring":
        if input == "1":
            session['step'] = 'cancel_recurring_pin'
            set_ussd_session(session_id, session)
            return USSDResponse("Enter 4 digit PIN")
        elif input == "2":
            set_ussd_session(session_id, {"stage": "main_menu"})
            return handle_main_menu(session_id, "", phone_number, db)
        else:
            return USSDResponse("Invalid option. Please try again.")
    
    elif step == "cancel_recurring_pin":
        if len(input) == 4:
            # Process cancellation
            return USSDResponse("Your request is being processed. You will receive an SMS on the status.", True)
        else:
            return USSDResponse("Invalid PIN. Enter 4-digit PIN:")
    
    elif step == "add_beneficiary":
        beneficiary_step = session.get('beneficiary_step', 'enter_name')
        
        if beneficiary_step == "enter_name":
            if input == "0":
                set_ussd_session(session_id, {"stage": "update_records", "step": "main"})
                return handle_update_records(session_id, "", inputs, phone_number, db)
            else:
                session['beneficiary_name'] = input
                session['beneficiary_step'] = 'enter_dob'
                set_ussd_session(session_id, session)
                return USSDResponse("Enter Beneficiary's DOB eg DDMMYYYY")
        
        elif beneficiary_step == "enter_dob":
            if input == "0":
                session['beneficiary_step'] = 'enter_name'
                set_ussd_session(session_id, session)
                return handle_update_records(session_id, "", inputs, phone_number, db)
            else:
                session['beneficiary_dob'] = input
                session['beneficiary_step'] = 'enter_phone'
                set_ussd_session(session_id, session)
                return USSDResponse("Enter Beneficiary's Phone Number or 0 to go back")
        
        elif beneficiary_step == "enter_phone":
            if input == "0":
                session['beneficiary_step'] = 'enter_dob'
                set_ussd_session(session_id, session)
                return handle_update_records(session_id, "", inputs, phone_number, db)
            else:
                session['beneficiary_phone'] = input
                session['beneficiary_step'] = 'enter_allocation'
                set_ussd_session(session_id, session)
                return USSDResponse("Enter Percentage Allocation. Total percentage is 100%")
        
        elif beneficiary_step == "enter_allocation":
            if input == "0":
                session['beneficiary_step'] = 'enter_phone'
                set_ussd_session(session_id, session)
                return handle_update_records(session_id, "", inputs, phone_number, db)
            else:
                try:
                    allocation = float(input)
                    session['beneficiary_allocation'] = allocation
                    session['beneficiary_step'] = 'confirm_details'
                    set_ussd_session(session_id, session)
                    
                    name = session.get('beneficiary_name', '')
                    dob = session.get('beneficiary_dob', '')
                    phone = session.get('beneficiary_phone', '')
                    
                    response = f"Confirm details of Beneficiary\nName: {name}\nDOB: {dob}\nPhone number: {phone}\n1. Confirm\n0. Back"
                    return USSDResponse(response)
                except ValueError:
                    return USSDResponse("Invalid percentage. Enter Percentage Allocation:")
        
        elif beneficiary_step == "confirm_details":
            if input == "1":
                session['beneficiary_step'] = 'confirm_allocation'
                set_ussd_session(session_id, session)
                
                allocation = session.get('beneficiary_allocation', 50)
                response = f"Would you like to allocate {allocation}% to {session.get('beneficiary_name', '')}?\n1. Yes\n0. Back"
                return USSDResponse(response)
            elif input == "0":
                session['beneficiary_step'] = 'enter_allocation'
                set_ussd_session(session_id, session)
                return handle_update_records(session_id, "", inputs, phone_number, db)
            else:
                return USSDResponse("Invalid option. Please try again.")
        
        elif beneficiary_step == "confirm_allocation":
            if input == "1":
                session['beneficiary_step'] = 'enter_pin'
                set_ussd_session(session_id, session)
                return USSDResponse("Enter 4 digit PIN")
            elif input == "0":
                session['beneficiary_step'] = 'confirm_details'
                set_ussd_session(session_id, session)
                return handle_update_records(session_id, "", inputs, phone_number, db)
            else:
                return USSDResponse("Invalid option. Please try again.")
        
        elif beneficiary_step == "enter_pin":
            if len(input) == 4:
                # Process beneficiary addition
                return USSDResponse("Your request has been successfully submitted. You will receive an SMS on your status", True)
            else:
                return USSDResponse("Invalid PIN. Enter 4-digit PIN:")
    
    return USSDResponse("Session completed.", True)



@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "USSD API"}
