"""Fills the Swagger test page with the live product catalog, so product, plan and tier
values can be picked instead of typed. Only the docs schema changes; the endpoints don't."""
import re
from typing import Optional

from app.routes.ussd import EBUSUA_PRODUCT

# Placeholders, not data: each fails validation if sent unchanged, so picking a product
# and pressing Execute without filling in the customer can't save anyone.
SAMPLE_CUSTOMER = {
    "phone_number": "ENTER-PHONE",
    "ghana_card": "ENTER-GHANA-CARD",
    "dob": "DDMMYYYY",
    "full_name": None,
    "registration_type": "self",
}


def _is_family(cfg: dict) -> bool:
    """Ebusua only: it's sold through the /ebusua endpoints. (The Sales App's is_family_plan flag
    is also set on ABS and Daakye, which the generic endpoints sell, so it isn't used here.)"""
    return cfg.get("name") == EBUSUA_PRODUCT


def _choices(catalog: dict, family: Optional[bool] = None):
    """One (product, plan, tier-or-None) per selectable combination. family=False leaves out
    family plans (sold only through the family-plan endpoints), True keeps only them."""
    for name, cfg in catalog.items():
        if family is not None and _is_family(cfg) != family:
            continue
        for ps in cfg.get("premium_structures", []):
            for tier in ps.get("tiers") or [None]:
                yield name, ps["premium_type"], tier


def _examples(catalog: dict, base: dict) -> dict:
    examples = {}
    for name, plan, tier in _choices(catalog, family=False):
        value = {**base, "product_name": name, "plan_type": plan}
        summary = f"{name} / {plan}"
        if tier:
            value["tier_value"] = str(tier["tier_value"])
            summary += f" / {tier['tier_name']}"
            if tier.get("premium_amount") is not None:
                summary += f" (GHS {float(tier['premium_amount']):,.2f})"
        value["frequency"] = "monthly"
        key = re.sub(r"[^a-z0-9]+", "-", f"{name} {plan} {tier['tier_value'] if tier else ''}".lower()).strip("-")
        examples[key] = {"summary": summary, "value": value}
    return examples


def _set_body_examples(paths: dict, path: str, examples: dict) -> None:
    content = paths.get(path, {}).get("post", {}).get("requestBody", {}).get("content", {}).get("application/json")
    if content is not None:
        content["examples"] = examples


def _set_param(paths: dict, path: str, name: str, enum: list, description: str = None) -> None:
    for param in paths.get(path, {}).get("get", {}).get("parameters", []):
        if param["name"] == name:
            param.setdefault("schema", {}).pop("anyOf", None)
            param["schema"].update({"type": "string", "enum": enum})
            if description:
                param["description"] = description


def add_catalog(schema: dict, catalog: dict) -> None:
    if not catalog:
        return
    paths = schema.get("paths", {})
    products = sorted(catalog)
    plans = sorted({plan for _, plan, _ in _choices(catalog)})
    tiers = sorted({str(t["tier_value"]) for _, _, t in _choices(catalog) if t}, key=lambda v: (len(v), v))
    combos = "\n".join(
        f"- {name}: " + "; ".join(
            f"plan `{ps['premium_type']}`, tiers " + (", ".join(f"`{t['tier_value']}` {t['tier_name']}" for t in ps.get("tiers", [])) or "none")
            for ps in cfg.get("premium_structures", []))
        for name, cfg in sorted(catalog.items()))

    _set_body_examples(paths, "/api/ussd/customers/onboard", _examples(catalog, SAMPLE_CUSTOMER))
    _set_body_examples(paths, "/api/ussd/policies/purchase", _examples(catalog, {"phone_number": SAMPLE_CUSTOMER["phone_number"]}))

    family = {}
    for name, plan, tier in _choices(catalog, family=True):
        n = re.fullmatch(r"\s*M\s*(?:\+\s*(\d+))?\s*", tier["tier_name"] if tier else "M", re.IGNORECASE) if tier else None
        if not n:
            continue
        count = int(n.group(1) or 0)
        price = f" (GHS {float(tier['premium_amount']):,.2f} a year)" if tier.get("premium_amount") is not None else ""
        family[f"{plan}-m{count}".lower()] = {
            "summary": f"{plan}, {tier['tier_name']}: holder + {count} family member{'s' if count != 1 else ''}{price}",
            "value": {**SAMPLE_CUSTOMER, "plan_type": plan, "family_members": count},
        }
    _set_body_examples(paths, "/api/ussd/ebusua/register", family)
    _set_body_examples(paths, "/api/ussd/ebusua/purchase", {k: {"summary": v["summary"], "value": {
        "phone_number": "ENTER-PHONE", "member_number": None, "plan_type": v["value"]["plan_type"],
        "family_members": v["value"]["family_members"], "agent_code": None}} for k, v in family.items()})
    _set_body_examples(paths, "/api/ussd/ebusua/members", {"family": {"summary": "A spouse and a child", "value": {
        "phone_number": "ENTER-HOLDER-PHONE", "policy_number": "ENTER-POLICY-NUMBER", "members": [
            {"relation": "spouse", "full_name": "ENTER-NAME", "dob": "DDMMYYYY", "ghana_card": "ENTER-GHANA-CARD", "phone_number": None},
            {"relation": "child", "full_name": "ENTER-NAME", "dob": "DDMMYYYY", "ghana_card": None, "phone_number": None}]}}})

    _set_body_examples(paths, "/api/ussd/payment-method", {
        "bank": {"summary": "Pay by bank", "value": {
            "phone_number": "ENTER-HOLDER-PHONE", "policy_number": "ENTER-POLICY-NUMBER", "payment_mode": "bank",
            "bank": {"bank_name": "ENTER-BANK", "branch": None, "account_name": "ENTER-ACCOUNT-NAME", "account_number": "ENTER-ACCOUNT-NUMBER"}}},
        "controller": {"summary": "Pay through the Controller (payroll deduction)", "value": {
            "phone_number": "ENTER-HOLDER-PHONE", "policy_number": "ENTER-POLICY-NUMBER", "payment_mode": "controller",
            "controller": {"staff_id": "ENTER-STAFF-ID", "employer": "ENTER-EMPLOYER", "management_unit": None}}},
    })

    for path in ("/api/ussd/products/{product_name}/benefits", "/api/ussd/products/{product_name}/pricing"):
        _set_param(paths, path, "product_name", products)
    pricing = "/api/ussd/products/{product_name}/pricing"
    _set_param(paths, pricing, "plan", plans, "Plan of the chosen product. Valid combinations:\n" + combos)
    _set_param(paths, pricing, "tier", tiers, "Tier of the chosen plan (see the plan description for which belong together).")
    _set_param(paths, pricing, "frequency", ["monthly", "quarterly", "half-yearly", "annually"])

    onboard = schema.get("components", {}).get("schemas", {}).get("OnboardRequest", {}).get("properties", {})
    if "product_name" in onboard:
        onboard["product_name"]["enum"] = [n for n in products if not _is_family(catalog[n])]
        onboard["plan_type"]["enum"] = sorted({plan for _, plan, _ in _choices(catalog, family=False)})
