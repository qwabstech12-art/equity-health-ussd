import httpx
from typing import Optional
from app.config.service import settings

BASE_URL = "https://ehi.equityhealthinsurance.com"
SMS_BASE_URL = "https://sms.hubtel.com/v1/messages/send"

async def make_one_time_payment(
    msisdn: str,
    amount: str,
    network: str,
    currency: str,
    ref_no: str,
) -> dict:

    url = f"{BASE_URL}/one-time/payment"
    payload = {
        "msisdn": msisdn,
        "amount": amount,
        "network": network,
        "currency": currency,
        "refNo": ref_no,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


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
   
    url = f"{BASE_URL}/mandate/payment"
    payload = {
        "clientPhone": client_phone,
        "amountToDebit": amount_to_debit,
        "frequencyType": frequency_type,
        "frequency": frequency,
        "startDate": start_date,
        "endDate": end_date,
        "debitDay": debit_day,
        "refNo": ref_no,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
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
