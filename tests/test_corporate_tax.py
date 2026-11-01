from datetime import date

import pandas as pd
import pytest

from corporate_tax import (
    classify_challan,
    compute_corporate_tax,
    interest_234b,
    interest_234c,
    round_to_10,
)
from tax_rules import get_tax_rules


def _df(rows):
    return pd.DataFrame(rows, columns=["Date", "Narration", "Withdrawal Amt.", "Deposit Amt."])


def test_round_to_10_follows_section_288a():
    assert round_to_10(2007458) == 2007460
    assert round_to_10(2007455) == 2007460
    assert round_to_10(2007454.99) == 2007450


@pytest.mark.parametrize(
    "when, expected_kind, expected_ay",
    [
        (date(2025, 3, 15), "advance", "2025-26"),
        (date(2024, 6, 10), "advance", "2025-26"),
        (date(2024, 10, 24), "self_assessment", "2024-25"),
        (date(2024, 12, 24), "self_assessment", "2024-25"),
    ],
)
def test_classify_challan_auto(when, expected_kind, expected_ay):
    result = classify_challan("K1", when, "2024-25", {})
    assert (result["kind"], result["ay"], result["auto"]) == (expected_kind, expected_ay, True)


def test_classify_challan_override_wins():
    result = classify_challan("K1", date(2025, 3, 15), "2024-25", {"K1": {"ay": "2024-25", "kind": "self_assessment"}})
    assert (result["kind"], result["ay"], result["auto"]) == ("self_assessment", "2024-25", False)


def test_interest_234c_fy2024_25_only_march_payment():
    # Tax 5,05,240; only 3,50,000 paid on 15-Mar-25
    result = interest_234c(505240, [(date(2025, 3, 15), 350000)], "2024-25")
    assert result == pytest.approx(2271 + 6819 + 11367 + 1552)


def test_interest_234c_none_when_instalments_paid_on_time():
    payments = [(date(2024, 6, 15), 15000), (date(2024, 9, 15), 30000), (date(2024, 12, 15), 30000), (date(2025, 3, 15), 25000)]
    assert interest_234c(100000, payments, "2024-25") == 0


def test_interest_234c_skips_due_dates_not_reached_yet():
    assert interest_234c(100000, [], "2025-26", today=date(2025, 7, 1)) == pytest.approx(15000 * 0.03)


def test_interest_234b():
    amount, months = interest_234b(505240, 350000, "2024-25", date(2025, 6, 30))
    assert months == 3
    assert amount == pytest.approx(155200 * 0.03)
    # No 234B when 90% was paid as advance tax
    assert interest_234b(100000, 95000, "2024-25", date(2025, 6, 30)) == (0.0, 0)


SAMPLE = _df([
    ("08/08/24", "RTGS CR-FUENFWERKEN DESIGN AG", 0, 1000000),
    ("04/11/24", "POS 403875 RVSL DT - 26/10/24", 0, 18768.93),
    ("15/08/24", "QUARTERLY INTEREST CREDIT 50301159165474", 0, 10000),
    ("16/08/24", "SWEEP-IN CREDIT - 50301159165474", 0, 50000),
    ("01/07/24", "NEFT DR-EMPLOYEE SALARY", 300000, 0),
    ("14/11/24", "NEFT DR-TANVIR KHAN-EU IN LOAN", 100000, 0),
    ("14/05/24", "FD THROUGH MOBILE-50301159165474:CO", 500000, 0),
    ("22/11/24", "TDS RECOVERY OF 50301159165474", 1000, 0),
    ("24/10/24", "CBDT/BANK REFERENCE NO:K2429826123728/CIN NO:X", 212540, 0),
    ("15/03/25", "CBDT/BANK REFERENCE NO:K2507432053009/CIN NO:Y", 100000, 0),
])


@pytest.fixture
def result():
    rules = get_tax_rules({"tax_rules": {"actuals": {"2024-25": {"self_assessment_paid_on": "2025-06-30"}}}})
    return compute_corporate_tax(SAMPLE, rules, "2024-25", today=date(2026, 1, 1))


def test_income_excludes_refunds_and_fd_principal(result):
    assert result["income"]["business"] == pytest.approx(1000000)
    assert result["income"]["fd_interest"] == pytest.approx(10000)
    reasons = {e["reason"]: e["amount"] for e in result["income"]["excluded"]}
    assert reasons["FD principal returned"] == pytest.approx(50000)
    assert sum(reasons.values()) == pytest.approx(50000 + 18768.93)


def test_expenses_exclude_loans_fd_tds_and_tax(result):
    assert result["expenses"]["deductible"] == pytest.approx(300000)
    reasons = {e["reason"] for e in result["expenses"]["excluded"]}
    assert {"Loan given (balance sheet item)", "FD investment (balance sheet item)",
            "TDS on FD interest (claimed as tax credit)", "Income tax payment"} <= reasons


def test_tax_computation(result):
    comp = result["computation"]
    assert comp["total_income"] == 710000
    assert comp["tax"] == round_to_10(710000 * 0.25168)
    assert result["credits"]["tds"] == pytest.approx(1000)
    # Only the March challan is advance tax for this year; October one was last year's self-assessment
    assert result["credits"]["advance_tax"] == pytest.approx(100000)


def test_payable_includes_interest(result):
    expected = result["computation"]["tax"] - 1000 - 100000 + result["interest"]["total"]
    assert result["payable"] == pytest.approx(expected)
    assert result["interest"]["234B_months"] == 3


def test_reconciliation_against_actuals():
    rules = get_tax_rules({"tax_rules": {"actuals": {"2024-25": {
        "advance_tax": 100000, "self_assessment_tax": 90000, "self_assessment_paid_on": "2025-06-30"}}}})
    rec = compute_corporate_tax(SAMPLE, rules, "2024-25", today=date(2026, 1, 1))["reconciliation"]
    paid = next(r for r in rec["rows"] if r["label"] == "Total tax + interest")
    assert paid["actual"] == pytest.approx(100000 + 90000 + 1000)
    assert paid["gap"] == pytest.approx(paid["engine"] - paid["actual"])


def test_planner_lists_four_instalments(result):
    planner = result["planner"]
    assert [p["percent"] for p in planner] == [15, 45, 75, 100]
    assert planner[-1]["paid_by"] == pytest.approx(100000)
