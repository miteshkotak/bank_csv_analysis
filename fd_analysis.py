"""Fixed Deposit (FD) detection and interest summary for HDFC bank statements."""
import re

import pandas as pd

FD_INTEREST = "FD Interest"
FD_TDS = "TDS on FD Interest"
FD_PRINCIPAL_RETURN = "FD Principal Return"
FD_BOOKING = "Financial / FD"

# Order matters: "FD REDEEM INTEREST" must be checked before generic FD rules.
FD_RULES = (
    (FD_INTEREST, ("QUARTERLY INTEREST CREDIT", "INT. ON SWCR", "FD REDEEM INTEREST", "FD INTEREST")),
    (FD_TDS, ("TAX RECOVERY FOR", "TDS RECOVERY", "TDS RECOVERED", "QUARTERLY TAX RECOVERED")),
    (FD_PRINCIPAL_RETURN, ("SWEEP-IN CREDIT", "FD REDEEM PRINCIPAL", "FD MATURITY", "FD CLOSURE")),
    (FD_BOOKING, ("FD THROUGH MOBILE", "FD BOOKED")),
)

# HDFC FD account numbers are 14 digits (e.g. 50301159165474)
FD_NUMBER_RE = re.compile(r"(?<!\d)(\d{14})(?!\d)")


def classify_fd_txn(narration: str) -> str | None:
    """Return the FD category for a narration, or None if it is not FD-related."""
    n = narration.upper()
    for category, keywords in FD_RULES:
        if any(k in n for k in keywords):
            return category
    return None


def extract_fd_number(narration: str) -> str | None:
    match = FD_NUMBER_RE.search(narration)
    return match.group(1) if match else None


def _amount(row: pd.Series) -> float:
    """FD bookings and TDS are debits; interest and principal returns are credits."""
    if row["FDType"] in (FD_BOOKING, FD_TDS):
        return float(row["Withdrawal Amt."])
    return float(row["Deposit Amt."])


def _sum(df: pd.DataFrame, fd_type: str) -> float:
    return float(df.loc[df["FDType"] == fd_type, "Amount"].sum())


def _deposit_summary(fd_number: str, rows: pd.DataFrame) -> dict:
    bookings = rows[rows["FDType"] == FD_BOOKING]
    interest_rows = rows[rows["FDType"] == FD_INTEREST]
    interest = _sum(rows, FD_INTEREST)
    tds = _sum(rows, FD_TDS)
    booked_on = bookings["DateObj"].min()
    last_credit = interest_rows["DateObj"].max()
    return {
        "fd_number": fd_number,
        "booked_on": booked_on.strftime("%Y-%m-%d") if pd.notna(booked_on) else None,
        "principal": _sum(rows, FD_BOOKING),
        "interest": interest,
        "tds": tds,
        "net_interest": interest - tds,
        "principal_returned": _sum(rows, FD_PRINCIPAL_RETURN),
        "credits": int(len(interest_rows)),
        "last_interest_on": last_credit.strftime("%Y-%m-%d") if pd.notna(last_credit) else None,
    }


def _monthly_summary(fd: pd.DataFrame) -> list[dict]:
    flows = fd[fd["FDType"].isin([FD_INTEREST, FD_TDS]) & fd["DateObj"].notna()]
    if flows.empty:
        return []
    pivot = (
        flows.assign(month=flows["DateObj"].dt.strftime("%Y-%m"))
        .pivot_table(index="month", columns="FDType", values="Amount", aggfunc="sum", fill_value=0)
        .sort_index()
    )
    return [
        {
            "month": month,
            "interest": float(row.get(FD_INTEREST, 0)),
            "tds": float(row.get(FD_TDS, 0)),
        }
        for month, row in pivot.iterrows()
    ]


def fd_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """Return only FD-related rows, with FDType, Amount, FDNumber and DateObj columns added.

    Expects columns: Date (dd/mm/yy), Narration, Withdrawal Amt., Deposit Amt.
    """
    fd = df.assign(FDType=df["Narration"].apply(classify_fd_txn))
    fd = fd[fd["FDType"].notna()]
    return fd.assign(
        Amount=fd.apply(_amount, axis=1) if not fd.empty else pd.Series(dtype=float),
        FDNumber=fd["Narration"].apply(extract_fd_number),
        DateObj=pd.to_datetime(fd["Date"], format="%d/%m/%y", errors="coerce"),
    )


def summarize_fd(df: pd.DataFrame) -> dict:
    """Build an FD interest summary from a statement DataFrame (see fd_transactions)."""
    fd = fd_transactions(df)

    gross_interest = _sum(fd, FD_INTEREST)
    tds = _sum(fd, FD_TDS)

    deposits = [
        _deposit_summary(fd_number, rows)
        for fd_number, rows in fd[fd["FDNumber"].notna()].groupby("FDNumber")
    ]
    deposits = sorted(deposits, key=lambda d: d["interest"], reverse=True)

    return {
        "totals": {
            "gross_interest": gross_interest,
            "tds": tds,
            "net_interest": gross_interest - tds,
            "effective_tds_rate": (tds / gross_interest * 100) if gross_interest else 0.0,
            "principal_booked": _sum(fd, FD_BOOKING),
            "principal_returned": _sum(fd, FD_PRINCIPAL_RETURN),
            "deposit_count": len(deposits),
        },
        "deposits": deposits,
        "monthly": _monthly_summary(fd),
    }
