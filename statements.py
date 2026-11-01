"""Bank statement storage: one CSV per financial year under files/statements/."""
import csv
import io
import pathlib
import re
import shutil

import pandas as pd

STATEMENTS_DIR = pathlib.Path("files/statements")
COLUMNS = ["Date", "Narration", "Chq/Ref.No.", "Value Dt", "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"]
AMOUNT_COLUMNS = ["Withdrawal Amt.", "Deposit Amt.", "Closing Balance"]
DATE_RE = re.compile(r"\d{2}/\d{2}/\d{2}")
FILE_RE = re.compile(r"^FY(\d{4}-\d{2})\.csv$")


class StatementError(ValueError):
    """Raised when an uploaded file is not a usable bank statement."""


def _parse_rows(lines) -> pd.DataFrame:
    rows = [row[:7] for row in csv.reader(lines) if row and DATE_RE.match(row[0]) and len(row) >= 7]
    df = pd.DataFrame(rows, columns=COLUMNS)
    for col in AMOUNT_COLUMNS:
        df[col] = pd.to_numeric(df[col].replace("", "0"), errors="coerce").fillna(0)
    return df


def parse_statement_csv(path: pathlib.Path) -> pd.DataFrame:
    """Read an HDFC statement CSV, keeping only transaction rows (those starting with dd/mm/yy)."""
    with path.open("r", encoding="utf-8", errors="replace") as f:
        return _parse_rows(f)


def detect_fy(df: pd.DataFrame) -> str | None:
    """Most common Apr-Mar financial year among the statement dates, e.g. "2024-25"."""
    dates = pd.to_datetime(df["Date"], format="%d/%m/%y", errors="coerce").dropna()
    if dates.empty:
        return None
    start_years = dates.apply(lambda d: d.year if d.month >= 4 else d.year - 1)
    start = int(start_years.mode().iloc[0])
    return f"{start}-{str(start + 1)[2:]}"


def fy_label(fy: str) -> str:
    return f"FY {fy}"


def statement_path(fy: str) -> pathlib.Path:
    return STATEMENTS_DIR / f"FY{fy}.csv"


def available_fys() -> list[str]:
    if not STATEMENTS_DIR.exists():
        return []
    fys = [m.group(1) for p in STATEMENTS_DIR.iterdir() if (m := FILE_RE.match(p.name))]
    return sorted(fys, reverse=True)


def load_raw(fy: str) -> pd.DataFrame | None:
    path = statement_path(fy)
    return parse_statement_csv(path) if path.exists() else None


def save_statement(content: bytes) -> str:
    """Store an uploaded statement under its financial year (replacing that year only). Returns the FY."""
    text = content.decode("utf-8", errors="replace")
    df = _parse_rows(io.StringIO(text))
    fy = detect_fy(df) if not df.empty else None
    if fy is None:
        raise StatementError("No transactions found. Please upload an HDFC statement exported as CSV.")
    STATEMENTS_DIR.mkdir(parents=True, exist_ok=True)
    statement_path(fy).write_text(text, encoding="utf-8")
    return fy


def migrate_legacy(legacy_path: pathlib.Path) -> None:
    """Copy the old single-file statement into per-year storage the first time the app starts."""
    if available_fys() or not legacy_path.exists():
        return
    fy = detect_fy(parse_statement_csv(legacy_path))
    if fy:
        STATEMENTS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(legacy_path, statement_path(fy))
