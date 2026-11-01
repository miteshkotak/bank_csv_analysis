import pandas as pd
import pytest

from fd_analysis import (
    FD_BOOKING,
    FD_INTEREST,
    FD_PRINCIPAL_RETURN,
    FD_TDS,
    classify_fd_txn,
    extract_fd_number,
    summarize_fd,
)


@pytest.mark.parametrize(
    "narration, expected",
    [
        ("QUARTERLY INTEREST CREDIT 50301159165474", FD_INTEREST),
        ("INT. ON SWCR ON-50301304445955", FD_INTEREST),
        ("FD REDEEM INTEREST -50301238793766/1", FD_INTEREST),
        ("FD INTEREST 50301159165474", FD_INTEREST),
        ("TAX RECOVERY FOR TD A/C 50301205526779  : DEPOSIT NO.1 50301205526779", FD_TDS),
        ("TAX RECOVERY FOR CUSTOMER 158823069 50301159165474", FD_TDS),
        ("TDS RECOVERY OF 50301149860438", FD_TDS),
        ("TDS RECOVERED ON-50301304445955", FD_TDS),
        ("QUARTERLY TAX RECOVERED 50301202967553", FD_TDS),
        ("SWEEP-IN CREDIT - 50301304445955", FD_PRINCIPAL_RETURN),
        ("FD REDEEM PRINCIPAL -50301238793766/1", FD_PRINCIPAL_RETURN),
        ("FD THROUGH MOBILE-50301149860438:EAST WEST DIGITAL PRIVATE LIMITED", FD_BOOKING),
        ("FD BOOKED - 50301304445955 : EAST WEST DIGITAL PRIVATE LIMITED", FD_BOOKING),
        ("BUSINESS CARD CASH BACK", None),
        ("UPI-LUFTHANSA-AIR TICKET", None),
    ],
)
def test_classify_fd_txn(narration, expected):
    assert classify_fd_txn(narration) == expected


def test_classify_is_case_insensitive():
    assert classify_fd_txn("quarterly interest credit 50301159165474") == FD_INTEREST


@pytest.mark.parametrize(
    "narration, expected",
    [
        ("TAX RECOVERY FOR CUSTOMER 158823069 50301159165474", "50301159165474"),
        ("FD REDEEM PRINCIPAL -50301238793766/1", "50301238793766"),
        ("INT. ON SWCR ON-50301304445955", "50301304445955"),
        ("BUSINESS CARD CASH BACK", None),
    ],
)
def test_extract_fd_number(narration, expected):
    assert extract_fd_number(narration) == expected


def _df(rows):
    return pd.DataFrame(rows, columns=["Date", "Narration", "Withdrawal Amt.", "Deposit Amt."])


SAMPLE = _df(
    [
        ("14/05/25", "FD THROUGH MOBILE-50301159165474:EAST WEST", 500000, 0),
        ("14/08/25", "QUARTERLY INTEREST CREDIT 50301159165474", 0, 7247),
        ("14/11/25", "QUARTERLY INTEREST CREDIT 50301159165474", 0, 7247),
        ("22/11/25", "TAX RECOVERY FOR CUSTOMER 158823069 50301159165474", 1457.3, 0),
        ("22/11/25", "TDS RECOVERY OF 50301149860438", 1459.9, 0),
        ("13/03/26", "FD REDEEM PRINCIPAL -50301238793766/1", 0, 500000),
        ("13/03/26", "FD REDEEM INTEREST -50301238793766/1", 0, 5145.3),
        ("02/05/25", "BUSINESS CARD CASH BACK", 0, 100),
    ]
)


def test_summarize_fd_totals():
    totals = summarize_fd(SAMPLE)["totals"]
    assert totals["gross_interest"] == pytest.approx(7247 * 2 + 5145.3)
    assert totals["tds"] == pytest.approx(1457.3 + 1459.9)
    assert totals["net_interest"] == pytest.approx(7247 * 2 + 5145.3 - 1457.3 - 1459.9)
    assert totals["principal_booked"] == pytest.approx(500000)
    assert totals["principal_returned"] == pytest.approx(500000)
    assert totals["deposit_count"] == 3


def test_summarize_fd_per_deposit():
    deposits = {d["fd_number"]: d for d in summarize_fd(SAMPLE)["deposits"]}
    fd = deposits["50301159165474"]
    assert fd["principal"] == pytest.approx(500000)
    assert fd["booked_on"] == "2025-05-14"
    assert fd["interest"] == pytest.approx(14494)
    assert fd["tds"] == pytest.approx(1457.3)
    assert fd["net_interest"] == pytest.approx(14494 - 1457.3)
    assert fd["credits"] == 2
    assert deposits["50301238793766"]["principal_returned"] == pytest.approx(500000)
    # Deposits are ordered by interest earned, highest first
    assert summarize_fd(SAMPLE)["deposits"][0]["fd_number"] == "50301159165474"


def test_summarize_fd_monthly():
    monthly = summarize_fd(SAMPLE)["monthly"]
    assert [m["month"] for m in monthly] == ["2025-08", "2025-11", "2026-03"]
    nov = monthly[1]
    assert nov["interest"] == pytest.approx(7247)
    assert nov["tds"] == pytest.approx(1457.3 + 1459.9)


def test_summarize_fd_empty():
    result = summarize_fd(_df([("02/05/25", "BUSINESS CARD CASH BACK", 0, 100)]))
    assert result["totals"]["gross_interest"] == 0
    assert result["totals"]["deposit_count"] == 0
    assert result["deposits"] == []
    assert result["monthly"] == []
