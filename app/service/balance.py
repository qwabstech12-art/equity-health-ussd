"""Works out what a policy owes from its premium, payment frequency, start date and the
payments received.

Rules:
- Premiums are paid in advance, in periods counted from the policy's start date. Each
  period's premium is due on its first day.
- A 12-month term has 12 monthly, 4 quarterly, 2 half-yearly or 1 annual period.
- Payments fill the oldest unpaid period first; anything beyond that is credit toward the
  next period."""
import calendar
from datetime import date, timedelta
from typing import List, Optional

PERIOD_MONTHS = {"monthly": 1, "quarterly": 3, "half-yearly": 6, "annually": 12}


def add_months(d: date, months: int) -> date:
    """Same day of the month, `months` later; the 31st becomes the last day of a shorter month."""
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _money(v: float) -> float:
    return round(v + 0.0, 2)


def policy_balance(premium: float, frequency: Optional[str], start: date, term_months: int,
                   payments: List[dict], today: date) -> dict:
    """`payments` are dicts with date, amount, method and transaction_id, oldest first."""
    frequency = frequency if frequency in PERIOD_MONTHS else "monthly"
    step = PERIOD_MONTHS[frequency]
    count = max(1, (term_months or 12) // step)
    total_paid = _money(sum(p["amount"] for p in payments))

    remaining = total_paid
    periods = []
    for i in range(count):
        p_start = add_months(start, i * step)
        p_end = add_months(start, (i + 1) * step) - timedelta(days=1)
        paid = min(premium, remaining)
        remaining = _money(remaining - paid)
        if p_start > today:
            status = "Upcoming"
        elif paid >= premium:
            status = "Paid"
        elif paid > 0:
            status = "Part paid"
        else:
            status = "Unpaid"
        periods.append({
            "period": i + 1, "start": p_start, "end": p_end,
            "due": _money(premium), "paid": _money(paid), "balance": _money(premium - paid), "status": status,
        })

    started = [p for p in periods if p["start"] <= today]
    current = next((p for p in started if p["end"] >= today), None)
    past = [p for p in started if p is not current]
    due_to_date = _money(premium * len(started))
    arrears = _money(sum(p["balance"] for p in past))
    due_now = _money(arrears + (current["balance"] if current else 0))
    upcoming = next((p for p in periods if p["start"] > today and p["balance"] > 0), None)

    return {
        "frequency": frequency,
        "total_paid": total_paid,
        "total_due_to_date": due_to_date,
        "arrears": arrears,
        "current_period": None if current is None else {
            k: current[k] for k in ("period", "start", "end", "due", "paid", "balance", "status")},
        "balance_due_now": due_now,
        "credit": _money(max(0.0, total_paid - due_to_date)),
        "next_due_date": upcoming["start"] if upcoming else None,
        "next_due_amount": upcoming["balance"] if upcoming else None,
        "term_ends": periods[-1]["end"],
        "periods": periods,
        "payments": payments,
    }


def ussd_line(policy_number: str, status: str, b: dict) -> str:
    """One short line per policy for a USSD screen."""
    def fmt(d: date) -> str:
        return d.strftime("%d %b")

    if status == "Pending" and b["total_paid"] == 0:
        return f"{policy_number}: Awaiting first payment of GHS {b['balance_due_now']:.2f}."
    if b["balance_due_now"] > 0:
        return f"{policy_number}: GHS {b['balance_due_now']:.2f} due now."
    if b["next_due_date"]:
        return f"{policy_number}: Paid up. Next GHS {b['next_due_amount']:.2f} due {fmt(b['next_due_date'])}."
    return f"{policy_number}: Fully paid to {fmt(b['term_ends'])}."
