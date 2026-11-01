"""Editable tax assumptions (stored in config.json under "tax_rules") and admin actions on them."""
import copy
import re
from datetime import datetime

RULE_LISTS = ("non_income", "non_deductible")
CHALLAN_KINDS = ("advance", "self_assessment")
ACTUAL_AMOUNT_FIELDS = ("advance_tax", "self_assessment_tax", "total_income", "net_tax", "interest", "taxes_paid")
YEAR_RE = re.compile(r"^\d{4}-\d{2}$")

DEFAULT_TAX_RULES = {
    # Section 115BAA: 22% base + 10% surcharge + 4% cess = 25.168%
    "regime": {"name": "Section 115BAA", "base_rate": 22.0, "surcharge": 10.0, "cess": 4.0},
    # Credits matching these are NOT income. Everything else credited is treated as income.
    "non_income": [
        {"keyword": "RVSL", "reason": "Card transaction reversal"},
        {"keyword": "CRV POS", "reason": "Card refund"},
        {"keyword": "REFUND", "reason": "Merchant refund"},
        {"keyword": "TXN FAILED", "reason": "Failed transaction refund"},
        {"keyword": "PUR ADJ", "reason": "Card purchase adjustment"},
    ],
    # Debits matching these are NOT deductible business expenses.
    "non_deductible": [
        {"keyword": "LOAN", "reason": "Loan given (balance sheet item)"},
        {"keyword": "SELF - CHQ", "reason": "Cash withdrawn"},
        {"keyword": "ATW-", "reason": "ATM cash withdrawal"},
    ],
    # Challan bank reference -> {"ay": "2024-25", "kind": "advance" | "self_assessment"}
    "tax_payments": {},
    # Financial year "2024-25" -> actual figures from the ITR / challans, used for reconciliation
    "actuals": {},
}


class TaxRuleError(ValueError):
    """Raised when an admin edit to the tax rules is invalid."""


def get_tax_rules(config: dict) -> dict:
    """Defaults overlaid with whatever the user saved. Saved keys replace defaults wholesale."""
    saved = config.get("tax_rules", {})
    rules = copy.deepcopy(DEFAULT_TAX_RULES)
    for key in rules:
        if key in saved:
            rules[key] = copy.deepcopy(saved[key])
    return rules


def effective_rate(regime: dict) -> float:
    """Effective tax rate in percent, e.g. 25.168 for 115BAA."""
    rate = regime["base_rate"] * (1 + regime["surcharge"] / 100) * (1 + regime["cess"] / 100)
    return round(rate, 4)


def match_rule(narration: str, rules: list[dict]) -> dict | None:
    n = narration.upper()
    return next((r for r in rules if r["keyword"].upper() in n), None)


def _percent(value: str, field: str) -> float:
    try:
        number = float(str(value).replace(",", "").strip())
    except ValueError:
        raise TaxRuleError(f"{field} must be a number") from None
    if not 0 <= number <= 100:
        raise TaxRuleError(f"{field} must be between 0 and 100")
    return number


def _amount(value: str, field: str) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        raise TaxRuleError(f"{field} must be a number") from None


def _rule_list(form: dict) -> str:
    name = form.get("list", "")
    if name not in RULE_LISTS:
        raise TaxRuleError(f"Unknown rule list: {name}")
    return name


def _keyword_and_reason(form: dict) -> tuple[str, str]:
    keyword = form.get("keyword", "").strip().upper()
    reason = form.get("reason", "").strip()
    if not keyword or not reason:
        raise TaxRuleError("Keyword and reason are required")
    return keyword, reason


def _year(value: str, field: str) -> str:
    if not YEAR_RE.match(value or ""):
        raise TaxRuleError(f"{field} must look like 2024-25")
    return value


def _add_rule(rules: dict, form: dict) -> dict:
    name = _rule_list(form)
    keyword, reason = _keyword_and_reason(form)
    if any(r["keyword"] == keyword for r in rules[name]):
        raise TaxRuleError(f"{keyword} already exists")
    return {**rules, name: [*rules[name], {"keyword": keyword, "reason": reason}]}


def _update_rule(rules: dict, form: dict) -> dict:
    name = _rule_list(form)
    original = form.get("original_keyword", "").strip().upper()
    keyword, reason = _keyword_and_reason(form)
    if keyword != original and any(r["keyword"] == keyword for r in rules[name]):
        raise TaxRuleError(f"{keyword} already exists")
    updated = [{"keyword": keyword, "reason": reason} if r["keyword"] == original else r for r in rules[name]]
    return {**rules, name: updated}


def _remove_rule(rules: dict, form: dict) -> dict:
    name = _rule_list(form)
    # Inline edit forms send the saved keyword as original_keyword; the visible field may have been edited
    keyword = (form.get("original_keyword") or form.get("keyword", "")).strip().upper()
    return {**rules, name: [r for r in rules[name] if r["keyword"] != keyword]}


def _update_regime(rules: dict, form: dict) -> dict:
    regime = {
        "name": form.get("name", "").strip() or "Custom",
        "base_rate": _percent(form.get("base_rate", ""), "Base rate"),
        "surcharge": _percent(form.get("surcharge", ""), "Surcharge"),
        "cess": _percent(form.get("cess", ""), "Cess"),
    }
    return {**rules, "regime": regime}


def _set_challan(rules: dict, form: dict) -> dict:
    ref = form.get("ref", "").strip()
    if not ref:
        raise TaxRuleError("Challan reference is required")
    payments = {k: v for k, v in rules["tax_payments"].items() if k != ref}
    kind = form.get("kind", "auto")
    if kind != "auto":
        if kind not in CHALLAN_KINDS:
            raise TaxRuleError(f"Unknown payment type: {kind}")
        payments[ref] = {"ay": _year(form.get("ay", ""), "Assessment year"), "kind": kind}
    return {**rules, "tax_payments": payments}


def _set_actuals(rules: dict, form: dict) -> dict:
    fy = _year(form.get("fy", ""), "Financial year")
    actual: dict = {}
    for field in ACTUAL_AMOUNT_FIELDS:
        value = str(form.get(field, "")).strip()
        if value:
            actual[field] = _amount(value, field.replace("_", " ").capitalize())
    paid_on = str(form.get("self_assessment_paid_on", "")).strip()
    if paid_on:
        try:
            datetime.strptime(paid_on, "%Y-%m-%d")
        except ValueError:
            raise TaxRuleError("Self-assessment paid on must be a date (YYYY-MM-DD)") from None
        actual["self_assessment_paid_on"] = paid_on
    actuals = {k: v for k, v in rules["actuals"].items() if k != fy}
    if actual:
        actuals[fy] = actual
    return {**rules, "actuals": actuals}


ACTIONS = {
    "add_rule": _add_rule,
    "update_rule": _update_rule,
    "remove_rule": _remove_rule,
    "update_regime": _update_regime,
    "set_challan": _set_challan,
    "set_actuals": _set_actuals,
}


def apply_rule_action(rules: dict, action: str, form: dict) -> dict:
    """Return a new rules dict with the admin action applied. Raises TaxRuleError on bad input."""
    if action not in ACTIONS:
        raise TaxRuleError(f"Unknown action: {action}")
    return ACTIONS[action](rules, form)
