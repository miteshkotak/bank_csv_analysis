import io

import pandas as pd
import pytest
from openpyxl import load_workbook

from fd_analysis import fd_transactions, summarize_fd
from fd_report import build_fd_report

SAMPLE = pd.DataFrame(
    [
        ("14/05/25", "FD THROUGH MOBILE-50301159165474:EAST WEST", 500000, 0),
        ("14/08/25", "QUARTERLY INTEREST CREDIT 50301159165474", 0, 7247),
        ("22/11/25", "TAX RECOVERY FOR CUSTOMER 158823069 50301159165474", 1457.3, 0),
        ("02/05/25", "BUSINESS CARD CASH BACK", 0, 100),
    ],
    columns=["Date", "Narration", "Withdrawal Amt.", "Deposit Amt."],
)


def test_fd_transactions_only_returns_fd_rows():
    txns = fd_transactions(SAMPLE)
    assert len(txns) == 3
    assert list(txns["FDNumber"].unique()) == ["50301159165474"]
    assert txns["Amount"].tolist() == pytest.approx([500000, 7247, 1457.3])


@pytest.fixture
def workbook():
    data = build_fd_report(summarize_fd(SAMPLE), fd_transactions(SAMPLE), period="FY 2025-26")
    return load_workbook(io.BytesIO(data))


def test_report_has_expected_sheets(workbook):
    assert workbook.sheetnames == ["Interest Summary", "FD Summary", "Monthly", "Transactions"]


def test_interest_summary_sheet(workbook):
    values = {row[0]: row[1] for row in workbook["Interest Summary"].iter_rows(values_only=True) if row[0]}
    assert values["Period"] == "FY 2025-26"
    assert values["Gross Interest"] == pytest.approx(7247)
    assert values["TDS Deducted"] == pytest.approx(1457.3)
    assert values["Net Interest"] == pytest.approx(7247 - 1457.3)


def test_fd_summary_sheet(workbook):
    rows = list(workbook["FD Summary"].iter_rows(values_only=True))
    assert rows[0][0] == "FD Number"
    assert rows[1][0] == "50301159165474"
    # Totals row at the bottom
    assert rows[-1][0] == "Total"


def test_transactions_sheet(workbook):
    rows = list(workbook["Transactions"].iter_rows(values_only=True))
    assert len(rows) == 4  # header + 3 FD rows
    assert rows[1][1] == "50301159165474"
