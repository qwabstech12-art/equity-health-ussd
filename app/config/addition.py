import re
import httpx
import random
from fastapi import HTTPException
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.config.service import settings

SALES_APP_BASE_URL = "https://salesapp.equityhealthinsurance.com"
SMS_BASE_URL = "https://sms.hubtel.com/v1/messages/send"

PRODUCT_METADATA = {
    "PROD-MICRO": {
        "benefits": [
            "Primary care only",
            "Medical consultations",
            "Laboratory [Primary care]",
            "Generic medications",
            "Optical conditions and aids (GHC 300) - 1 year waiting period",
            "Dental conditions and procedures",
            "Monthly benefits",
            "Benefits are not accrued",
            "Maternity cover (2,000) - 1 year waiting period"
        ],
        "waiting_periods": {
            "optical": "1 year",
            "maternity": "1 year"
        }
    },
    "PROD-NHIS-TOPUP": {
        "benefits": [
            "Medical consultations",
            "Laboratory Investigations",
            "Basic Imaging (x-ray, ultrasound, ECG, Endoscopy, EEG, Echo)",
            "Generic medications",
            "Optical Aid (Eye conditions)",
            "Dental conditions",
            "Monthly benefits",
            "Medication (Drugs not covered under NHIS)",
            "Benefits are not accrued"
        ]
    },
    "PROD-TELEMED": {
        "benefits": [
            "Medical consultation via telephone, 3 times each month, and 30 times per year",
            "Begin accessing services immediately after subscription and payment",
            "Quick and easy access to medication",
            "Get lab tests prescribed remotely",
            "Referrals to specialists (when necessary)",
            "Free medicine delivery when available"
        ]
    },
    "PROD-ABS": {
        "benefits": [
            "Telemedicine consultation",
            "Medication",
            "Free medication delivery service",
            "Health screening"
        ]
    },
    "PROD-EBUSUA": {
        "benefits": [
            "Telemedicine consultation",
            "Medication",
            "Free medication delivery service",
            "Health screening"
        ]
    },
    "PROD-DAAKYE-APOMUDEN": {
        "benefits": [
            "Lifetime Healthcare",
            "Standard healthcare benefits"
        ]
    }
}

async def fetch_insurance_products() -> list:
    """Fetch active insurance products from the sales app API"""
    url = f"{SALES_APP_BASE_URL}/api/insurance/insurance-products/"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()

async def fetch_product_details(product_id: str) -> dict:
    """Fetch detailed plan and pricing information for a product"""
    url = f"{SALES_APP_BASE_URL}/insurance/products/insurance/product-details/{product_id}"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()

async def get_dynamic_policy_config() -> dict:
    """Orchestrate API fetching and mapping into USSD POLICY_CONFIG format with Name as key"""
    try:
        products = await fetch_insurance_products()
        dynamic_config = {}

        for prod in products:
            code = prod.get("productCode")
            metadata = PRODUCT_METADATA.get(code, {"benefits": []})

            details = await fetch_product_details(prod["_id"])
            prod_name = prod["name"]

            config_entry = {
                "id": prod["_id"],
                "productCode": code,
                "name": prod_name,
                "benefits": metadata["benefits"],
                "waiting_periods": metadata.get("waiting_periods", {}),
                "details": details,
                "premium_structures": details.get("premium_structures", []),
                "product_plan": details.get("product_plan", {}),
                "loadings": details.get("loadings", [])
            }

            dynamic_config[prod_name] = config_entry

        return dynamic_config
    except Exception as e:
        print(f"Error fetching dynamic policy config: {e}")
        return {}

def calculate_premium_dynamic(
    product_config: dict,
    plan_type: str,
    tier_value: str = None,
    frequency: str = "monthly",
    dob: str = None,
    medical_conditions: list = None
) -> dict:
    """
    Implements the premium calculation logic from the frontend React code.
    Returns a dict with 'total', 'sum_assured', and 'breakdown'.
    """
    if not product_config or not plan_type:
        return {"total": 0.0, "sum_assured": 0}

    base_premium = 0
    sum_assured = 0

    # 1. Find the selected premium structure
    premium_structures = product_config.get("premium_structures", [])
    p_struct = next((ps for ps in premium_structures if ps["premium_type"] == plan_type), None)

    if not p_struct:
        return {"total": 0.0, "sum_assured": 0}

    # 2. Get base premium and policy fee
    # (`or 0` guards against the API returning an explicit null, which
    # bypasses dict.get's default -- the default only applies when the key
    # is missing entirely, not when its value is None.)
    base_premium = p_struct.get("base_premium", 0) or 0
    base_premium += p_struct.get("policy_fee", 0) or 0

    # 3. Apply tier if provided
    tier = None
    if tier_value:
        tiers = p_struct.get("tiers", [])
        tier = next((t for t in tiers if str(t["tier_value"]) == str(tier_value)), None)
        if tier:
            base_premium = tier.get("premium_amount") if tier.get("premium_amount") is not None else base_premium
            sum_assured = tier.get("sum_assured", 0) or 0

    # 4. Apply loadings (Age Loading)
    loadings = product_config.get("loadings", [])
    if dob:
        age_loading = next((l for l in loadings if l["loading_type"] == "age_loading"), None)
        if age_loading and age_loading.get("conditions"):
            try:
                # Expecting dob in DDMMYYYY from USSD
                birth_date = datetime.strptime(dob, "%d%m%Y")
                today = datetime.now()
                age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))

                age_cond = next((c for c in age_loading["conditions"] if c["condition_field"] == "age"), None)
                if age_cond:
                    apply = False
                    if age_cond["operator"] == ">" and age > int(age_cond["value1"]):
                        apply = True
                    elif age_cond["operator"] == "between" and int(age_cond["value1"]) <= age <= int(age_cond["value2"]):
                        apply = True
                    elif age_cond["operator"] == ">=" and age >= int(age_cond["value1"]):
                        apply = True

                    if apply:
                        if age_loading["calculation_method"] == "percentage":
                            base_premium += base_premium * (age_loading["value"] / 100)
                        elif age_loading["calculation_method"] == "fixed":
                            base_premium += age_loading["value"]
            except:
                pass

    # 5. Frequency multiplier. A yearly price already covers the whole year, so it's paid once
    # a year: the frequency is set to annually whatever was asked for, and it isn't multiplied.
    yearly = is_yearly_price(product_config.get("name"), tier)
    if frequency == "yearly" or yearly:
        frequency = "annually"
    multiplier = 1 if yearly else {"quarterly": 3, "half-yearly": 6, "annually": 12}.get(frequency, 1)

    total = base_premium * multiplier

    return {
        "total": float(total),
        "sum_assured": float(sum_assured),
        "base_premium": float(base_premium),
        "multiplier": multiplier,
        "frequency": frequency,
        "price_period": "yearly" if yearly else "monthly",
    }


# Products whose prices cover a whole year even though their tier names don't say so.
YEARLY_PRODUCTS = {"Ebusua Health"}
YEARLY_TIER_NAME = re.compile(r"\b(year|yearly|annual|annually)\b", re.IGNORECASE)


def is_yearly_price(product_name: str, tier: dict = None) -> bool:
    """True if the catalog price is for a year: the whole product is priced yearly, or the
    tier's name says Yearly/Annually (e.g. "Level 1 Annually"). Everything else is monthly."""
    if product_name in YEARLY_PRODUCTS:
        return True
    return bool(tier and YEARLY_TIER_NAME.search(tier.get("tier_name") or ""))

async def make_one_time_payment(
    msisdn: str,
    amount: str,
    network: str,
    currency: str,
    ref_no: str,
) -> dict:
    """One-time mobile-money debit via Uniwallet -- calls the gateway directly
    (no longer proxies through the separate ehi_payment service). Ports the
    233-prefix MSISDN normalization and the bounded duplicate-refNo retry loop
    from that service's implementation."""
    base_ref = ref_no
    current_ref = ref_no

    if msisdn.startswith("0"):
        msisdn = "233" + msisdn[1:]

    headers = {
        "x-key": settings.UNIWALLET_X_KEY,
        "x-country": settings.UNIWALLET_X_COUNTRY,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        for _ in range(5):
            payload = {
                "refNo": current_ref,
                "productId": settings.UNIWALLET_PRODUCT_ID,
                "transflowId": settings.UNIWALLET_TRANSFLOW_ID,
                "msisdn": msisdn,
                "network": network,
                "amount": amount,
                "narration": "Equity Health Insurance",
                "additionalRef": ref_no,
                "currency": currency,
            }
            response = await client.post(
                f"{settings.UNIWALLET_BASE_URL}/uniwallet/v2/debit", headers=headers, json=payload,
            )
            data = response.json()

            if data.get("responseCode") == "03":
                return {"data": data, "refNo": current_ref}
            if "Duplicate transaction request" in data.get("responseMessage", ""):
                current_ref = f"{base_ref}_{random.randint(1, 9999)}"
                continue
            raise HTTPException(status_code=400, detail=data)

    raise HTTPException(status_code=400, detail="Max retry attempts reached")


async def make_mandate_payment(
    client_phone: str,
    amount_to_debit: str,
    frequency_type: str,
    frequency: str,
    start_date: str,
    end_date: str,
    debit_day: str,
    ref_no: str,
) -> dict:
    """Create a Transflow recurring-debit mandate -- calls the gateway directly
    (no longer proxies through the separate ehi_payment service)."""
    payload = {
        "merchantId": settings.TRANSFLOW_MERCHANT_ID,
        "productId": settings.TRANSFLOW_PRODUCT_ID,
        "clientPhone": client_phone,
        "amountToDebit": amount_to_debit,
        "frequencyType": frequency_type,
        "frequency": frequency,
        "startDate": start_date,
        "endDate": end_date,
        "debitDay": debit_day,
        "apiKey": settings.TRANSFLOW_API_KEY,
        "thirdPartyReferenceNo": ref_no,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.TRANSFLOW_BASE_URL}/create/mandate",
            headers={"Content-Type": "application/json"}, json=payload,
        )
        data = response.json()
        # "03" == mandate request accepted/pending -- Transflow's mandate creation
        # is itself async; it only becomes fully active later via a callback with
        # responseCode "01" (see /payments/callbacks/mandate).
        if data.get("responseCode") != "03":
            raise HTTPException(status_code=400, detail=data.get("responseMessage", "Failed to initialize mandate"))
        return data


async def get_mandate_details(phone_number: str, date: Optional[str] = None) -> dict:
    """Single-call mandate details lookup from Transflow (no polling loop)."""
    url = f"{settings.TRANSFLOW_BASE_URL}/retrieve-mandate/details/{phone_number}/{settings.TRANSFLOW_MERCHANT_ID}"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        data = response.json()

    if not isinstance(data, list):
        return {"found": False, "data": data}
    if date:
        data = [item for item in data if item.get("startDate") == date]
    return {"found": bool(data), "data": data}


async def check_uniwallet_transaction_status(ref_no: str) -> dict:
    """Single-call Uniwallet transaction status check (no polling loop)."""
    payload = {"productId": settings.UNIWALLET_PRODUCT_ID, "transflowId": settings.UNIWALLET_TRANSFLOW_ID}
    headers = {
        "x-key": settings.UNIWALLET_X_KEY,
        "x-country": settings.UNIWALLET_X_COUNTRY,
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.UNIWALLET_BASE_URL}/uniwallet/v2/check-transaction-status/{ref_no}",
            headers=headers, json=payload,
        )
        return response.json()


async def send_sms(
    to_number: str,
    message: str,
) -> dict:
   
    params = {
        "clientid": settings.client_id,
        "clientsecret": settings.sms_secrete,
        "from": "Equity",
        "to": to_number,
        "content": message.replace(' ', '+'),
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(SMS_BASE_URL, params=params)
        response.raise_for_status()
        return response.json()
