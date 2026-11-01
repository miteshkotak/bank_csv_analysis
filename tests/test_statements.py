import pandas as pd
import pytest

import statements
from statements import StatementError, detect_fy, parse_statement_csv

CSV = """HDFC BANK Ltd.
Date,Narration,Chq./Ref.No.,Value Dt,Withdrawal Amt.,Deposit Amt.,Closing Balance
01/04/24,POS GF ECOM,0001,01/04/24,56289.18,,688584.63
15/03/25,CBDT/BANK REFERENCE NO:K2507432053009/CIN NO:X,0002,15/03/25,350000,,100
31/03/25,RTGS CR-CLIENT,0003,31/03/25,,1000,1100
Opening Balance,,,,Debits,Credits,Closing Bal
"""


@pytest.fixture
def statement_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(statements, "STATEMENTS_DIR", tmp_path / "statements")
    return tmp_path


def test_parse_statement_csv_keeps_only_transaction_rows(tmp_path):
    path = tmp_path / "s.csv"
    path.write_text(CSV)
    df = parse_statement_csv(path)
    assert len(df) == 3
    assert df["Withdrawal Amt."].tolist() == [56289.18, 350000, 0]
    assert df["Deposit Amt."].tolist() == [0, 0, 1000]


def test_detect_fy_uses_most_common_financial_year():
    df = pd.DataFrame({"Date": ["01/04/24", "15/03/25", "31/03/25", "02/04/25"]})
    assert detect_fy(df) == "2024-25"
    assert detect_fy(pd.DataFrame({"Date": ["bad"]})) is None


def test_save_statement_stores_one_file_per_fy(statement_dir):
    fy = statements.save_statement(CSV.encode())
    assert fy == "2024-25"
    assert statements.available_fys() == ["2024-25"]
    assert statements.load_raw("2024-25")["Narration"].iloc[0] == "POS GF ECOM"


def test_save_statement_rejects_files_without_transactions(statement_dir):
    with pytest.raises(StatementError):
        statements.save_statement(b"just,a,header\n")


def test_migrate_legacy_copies_single_csv_once(statement_dir):
    legacy = statement_dir / "easy_withdrawl.csv"
    legacy.write_text(CSV)
    statements.migrate_legacy(legacy)
    assert statements.available_fys() == ["2024-25"]
    statements.migrate_legacy(legacy)  # idempotent
    assert statements.available_fys() == ["2024-25"]


def test_available_fys_sorted_latest_first(statement_dir):
    statements.save_statement(CSV.encode())
    statements.save_statement(CSV.replace("/24", "/25").replace("/25,", "/26,").encode())
    assert statements.available_fys() == ["2025-26", "2024-25"]
