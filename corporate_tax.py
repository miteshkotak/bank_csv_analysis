"""Corporate income tax estimate from a bank statement, driven by the editable rules in tax_rules."""
import math
import re
from datetime import date, datetime

import pandas as pd

from fd_analysis import (
    FD_BOOKING,
    FD_INTEREST,
    FD_PRINCIPAL_RETURN,
    FD_TDS,
    fd_transactions,
)
from tax_rules import effective_rate, match_rule

# Advance tax instalments: (month, day, cumulative %, % that avoids 234C, months of interest)
INSTALMENTS = ((6, 15, 15, 12, 3), (9, 15, 45, 36, 3), (12, 15, 75, 75, 3), (3, 15, 100, 100, 1))
# Challans paid inside these windows are assumed to be advance tax: (month, last day)
ADVANCE_WINDOWS = ((6, 15), (9, 15), (12, 15), (3, 31))
CHALLAN_REF_RE = re.compile(r"BANK REFERENCE NO:(\w+)")
MATCH_TOLERANCE_PCT = 2.0

INCOME, FD_INCOME, INCOME_EXCLUDED, EXPENSE, EXPENSE_EXCLUDED = (
    "income", "fd_interest", "income_excluded", "expense", "expense_excluded")


def round_to_10(amount: float) -> int:
    """Sections 288A/288B: round to the nearest multiple of 10 (5 rounds up)."""
    return int(math.floor((amount + 5) / 10) * 10)


def _floor_100(amount: float) -> float:
    """Rule 119A: interest is computed on amounts rounded down to the nearest 100."""
    return math.floor(amount / 100) * 100


def _fy_start(fy: str) -> int:
    return int(fy[:4])


def assessment_year(fy: str) -> str:
    start = _fy_start(fy) + 1
    return f"{start}-{str(start + 1)[2:]}"


def _due_date(fy: str, month: int, day: int) -> date:
    start = _fy_start(fy)
    return date(start + 1 if month < 4 else start, month, day)


def classify_challan(ref: str, when: date, fy: str, overrides: dict) -> dict:
    """Which assessment year and payment type a CBDT challan belongs to (admin override wins)."""
    if ref in overrides:
        return {**overrides[ref], "auto": False}
    in_window = any(when.month == m and when.day <= last for m, last in ADVANCE_WINDOWS)
    if in_window:
        return {"ay": assessment_year(fy), "kind": "advance", "auto": True}
    # Outside instalment windows: most likely last year's self-assessment tax (AY string == this FY string)
    return {"ay": fy, "kind": "self_assessment", "auto": True}


def interest_234c(assessed: float, payments: list[tuple[date, float]], fy: str, today: date | None = None) -> float:
    """Interest for deferring advance tax instalments."""
    if assessed < 10000:
        return 0.0
    total = 0.0
    for month, day, percent, safe_percent, months in INSTALMENTS:
        due = _due_date(fy, month, day)
        if today and due > today:
            continue
        paid = sum(amount for when, amount in payments if when <= due)
        if paid >= assessed * safe_percent / 100:
            continue
        shortfall = assessed * percent / 100 - paid
        total += _floor_100(shortfall) * 0.01 * months
    return total


def interest_234b(assessed: float, advance_total: float, fy: str, paid_on: date | None) -> tuple[float, int]:
    """Interest when advance tax paid is below 90% of assessed tax. Returns (amount, months)."""
    ay_start = date(_fy_start(fy) + 1, 4, 1)
    if assessed < 10000 or advance_total >= 0.9 * assessed or paid_on is None or paid_on < ay_start:
        return 0.0, 0
    months = (paid_on.year - ay_start.year) * 12 + paid_on.month - ay_start.month + 1
    return _floor_100(assessed - advance_total) * 0.01 * months, months


def _treatment(narration: str, withdrawal: float, fd_type: str | None, rules: dict) -> tuple[str, str]:
    if withdrawal > 0:
        if "CBDT" in narration.upper():
            return EXPENSE_EXCLUDED, "Income tax payment"
        if fd_type == FD_BOOKING:
            return EXPENSE_EXCLUDED, "FD investment (balance sheet item)"
        if fd_type == FD_TDS:
            return EXPENSE_EXCLUDED, "TDS on FD interest (claimed as tax credit)"
        rule = match_rule(narration, rules["non_deductible"])
        return (EXPENSE_EXCLUDED, rule["reason"]) if rule else (EXPENSE, "")
    if fd_type == FD_INTEREST:
        return FD_INCOME, ""
    if fd_type == FD_PRINCIPAL_RETURN:
        return INCOME_EXCLUDED, "FD principal returned"
    rule = match_rule(narration, rules["non_income"])
    return (INCOME_EXCLUDED, rule["reason"]) if rule else (INCOME, "")


def classify_transactions(df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    """Add Treatment, Reason and Amount columns describing how each row is treated for tax."""
    fd_types = fd_transactions(df)["FDType"].reindex(df.index)
    treatments = [
        _treatment(n, w, t if isinstance(t, str) else None, rules)
        for n, w, t in zip(df["Narration"], df["Withdrawal Amt."], fd_types)
    ]
    return df.assign(
        Treatment=[t for t, _ in treatments],
        Reason=[r for _, r in treatments],
        Amount=df["Withdrawal Amt."].where(df["Withdrawal Amt."] > 0, df["Deposit Amt."]),
    )


def _excluded_summary(rows: pd.DataFrame) -> list[dict]:
    if rows.empty:
        return []
    grouped = rows.groupby("Reason")["Amount"].agg(["sum", "count"]).sort_values("sum", ascending=False)
    return [{"reason": r, "amount": float(g["sum"]), "count": int(g["count"])} for r, g in grouped.iterrows()]


def _excluded_rows(rows: pd.DataFrame) -> list[dict]:
    return [
        {"date": d, "narration": n, "amount": float(a), "reason": r}
        for d, n, a, r in zip(rows["Date"], rows["Narration"], rows["Amount"], rows["Reason"])
    ]


def _category_breakdown(tx: pd.DataFrame) -> list[dict]:
    if "Category" not in tx.columns:
        return []
    spend = tx[tx["Treatment"].isin([EXPENSE, EXPENSE_EXCLUDED])]
    rows = [
        {"Category": cat, "Amount": float(g["Amount"].sum()),
         "Deductible": float(g.loc[g["Treatment"] == EXPENSE, "Amount"].sum())}
        for cat, g in spend.groupby("Category")
    ]
    return sorted(rows, key=lambda r: r["Amount"], reverse=True)


def list_challans(tx: pd.DataFrame, fy: str, rules: dict) -> list[dict]:
    """CBDT payments in the statement with the assessment year and type each is counted towards."""
    rows = tx[(tx["Withdrawal Amt."] > 0) & tx["Narration"].str.upper().str.contains("CBDT")]
    challans = []
    for d, narration, amount in zip(rows["Date"], rows["Narration"], rows["Withdrawal Amt."]):
        when = datetime.strptime(d, "%d/%m/%y").date()
        match = CHALLAN_REF_RE.search(narration)
        ref = match.group(1) if match else f"{d}-{amount:.0f}"
        challans.append({"ref": ref, "date": when.isoformat(), "amount": float(amount),
                         **classify_challan(ref, when, fy, rules["tax_payments"])})
    return challans


def _tax_on(total_income: int, regime: dict) -> dict:
    base = total_income * regime["base_rate"] / 100
    surcharge = base * regime["surcharge"] / 100
    cess = (base + surcharge) * regime["cess"] / 100
    return {"base_tax": base, "surcharge": surcharge, "cess": cess, "tax": round_to_10(base + surcharge + cess)}


def _planner(assessed: float, payments: list[tuple[date, float]], fy: str, today: date) -> list[dict]:
    plan = []
    for month, day, percent, _, _ in INSTALMENTS:
        due = _due_date(fy, month, day)
        required = assessed * percent / 100
        paid = sum(amount for when, amount in payments if when <= due)
        status = "upcoming" if due > today else ("paid" if paid >= required else "short")
        plan.append({"due": due.isoformat(), "percent": percent, "required": required,
                     "paid_by": paid, "shortfall": max(0.0, required - paid), "status": status})
    return plan


def _reconciliation(actual: dict, engine: dict) -> dict | None:
    if not actual:
        return None
    candidates = [
        ("Total income", engine["total_income"], actual.get("total_income")),
        ("Net tax", engine["tax"], actual.get("net_tax")),
        ("Interest (234B/234C)", engine["interest"], actual.get("interest")),
    ]
    paid = actual.get("taxes_paid")
    if paid is None and ("advance_tax" in actual or "self_assessment_tax" in actual):
        # Taxes paid = advance + self-assessment + TDS (TDS comes from the statement)
        paid = actual.get("advance_tax", 0) + actual.get("self_assessment_tax", 0) + engine["tds"]
    candidates.append(("Total tax + interest", engine["tax"] + engine["interest"], paid))
    compared = [(label, float(e), float(a)) for label, e, a in candidates if a is not None]
    gap_pcts = [(e - a) / a * 100 if a else 0.0 for _, e, a in compared]
    rows = [
        {"label": label, "engine": e, "actual": a, "gap": e - a, "gap_pct": pct}
        for (label, e, a), pct in zip(compared, gap_pcts)
    ]
    matched = all(abs(pct) <= MATCH_TOLERANCE_PCT for pct in gap_pcts)
    return {"rows": rows, "status": "match" if matched else "review", "tolerance_pct": MATCH_TOLERANCE_PCT}


def _self_assessment_date(actual: dict, fy: str, today: date) -> date | None:
    if actual.get("self_assessment_paid_on"):
        return datetime.strptime(actual["self_assessment_paid_on"], "%Y-%m-%d").date()
    # Not paid yet: interest keeps running until today once the assessment year has started
    return today if today >= date(_fy_start(fy) + 1, 4, 1) else None


def compute_corporate_tax(df: pd.DataFrame, rules: dict, fy: str, today: date | None = None) -> dict:
    today = today or date.today()
    tx = classify_transactions(df, rules)
    by = tx.groupby("Treatment")["Amount"].sum()
    business, fd_interest, deductible = (float(by.get(k, 0.0)) for k in (INCOME, FD_INCOME, EXPENSE))
    tds = float(tx.loc[tx["Reason"] == "TDS on FD interest (claimed as tax credit)", "Amount"].sum())

    total_income = max(0, round_to_10(business + fd_interest - deductible))
    regime = rules["regime"]
    tax = _tax_on(total_income, regime)

    challans = list_challans(tx, fy, rules)
    ay = assessment_year(fy)
    advance = [(date.fromisoformat(c["date"]), c["amount"]) for c in challans if c["kind"] == "advance" and c["ay"] == ay]
    advance_total = sum(a for _, a in advance)

    assessed = max(0.0, tax["tax"] - tds)
    actual = rules["actuals"].get(fy, {})
    sat_date = _self_assessment_date(actual, fy, today)
    i234c = interest_234c(assessed, advance, fy, today=today)
    i234b, months = interest_234b(assessed, advance_total, fy, sat_date)
    interest = i234b + i234c

    income_excluded = tx[tx["Treatment"] == INCOME_EXCLUDED]
    expense_excluded = tx[tx["Treatment"] == EXPENSE_EXCLUDED]
    return {
        "fy": fy,
        "ay": ay,
        "regime": {**regime, "effective_rate": effective_rate(regime)},
        "income": {"business": business, "fd_interest": fd_interest, "total": business + fd_interest,
                   "excluded": _excluded_summary(income_excluded)},
        "expenses": {"deductible": deductible, "excluded": _excluded_summary(expense_excluded),
                     "by_category": _category_breakdown(tx)},
        "excluded_transactions": _excluded_rows(pd.concat([income_excluded, expense_excluded])),
        "computation": {"profit": business + fd_interest - deductible, "total_income": total_income, **tax},
        "credits": {"tds": tds, "advance_tax": advance_total},
        "interest": {"234C": i234c, "234B": i234b, "234B_months": months,
                     "self_assessment_date": sat_date.isoformat() if sat_date else None, "total": interest},
        "payable": tax["tax"] - tds - advance_total + interest,
        "challans": challans,
        "planner": _planner(assessed, advance, fy, today),
        "reconciliation": _reconciliation(actual, {"total_income": total_income, "tax": tax["tax"],
                                                   "interest": interest, "tds": tds}),
    }
