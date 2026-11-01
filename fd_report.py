"""Excel export of the FD interest summary."""
import io

import pandas as pd
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from fd_analysis import FD_BOOKING

MONEY_FORMAT = "₹#,##,##0.00"
HEADER_FILL = PatternFill("solid", fgColor="1E293B")
HEADER_FONT = Font(bold=True, color="FFFFFF")


def _interest_summary_frame(summary: dict, period: str) -> pd.DataFrame:
    t = summary["totals"]
    rows = [
        ("Period", period),
        ("Fixed Deposits", t["deposit_count"]),
        ("Gross Interest", t["gross_interest"]),
        ("TDS Deducted", t["tds"]),
        ("Net Interest", t["net_interest"]),
        ("Effective TDS Rate (%)", round(t["effective_tds_rate"], 2)),
        ("Principal Invested", t["principal_booked"]),
        ("Principal Returned (sweep-in & redemptions)", t["principal_returned"]),
    ]
    return pd.DataFrame(rows, columns=["Metric", "Value"])


def _fd_summary_frame(summary: dict) -> pd.DataFrame:
    df = pd.DataFrame(
        summary["deposits"],
        columns=["fd_number", "booked_on", "principal", "interest", "tds", "net_interest",
                 "principal_returned", "credits", "last_interest_on"],
    ).rename(columns={
        "fd_number": "FD Number", "booked_on": "Booked On", "principal": "Principal",
        "interest": "Gross Interest", "tds": "TDS", "net_interest": "Net Interest",
        "principal_returned": "Principal Returned", "credits": "Interest Credits",
        "last_interest_on": "Last Interest On",
    })
    totals = {"FD Number": "Total"}
    for col in ["Principal", "Gross Interest", "TDS", "Net Interest", "Principal Returned", "Interest Credits"]:
        totals[col] = df[col].sum()
    return pd.concat([df, pd.DataFrame([totals])], ignore_index=True)


def _monthly_frame(summary: dict) -> pd.DataFrame:
    df = pd.DataFrame(summary["monthly"], columns=["month", "interest", "tds"])
    return df.assign(net=df["interest"] - df["tds"]).rename(
        columns={"month": "Month", "interest": "Gross Interest", "tds": "TDS", "net": "Net Interest"}
    )


def _transactions_frame(txns: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "Date": txns["DateObj"].dt.strftime("%Y-%m-%d"),
        "FD Number": txns["FDNumber"],
        "Type": txns["FDType"].replace({FD_BOOKING: "FD Booking"}),
        "Amount": txns["Amount"],
        "Narration": txns["Narration"],
    }).sort_values("Date", kind="stable")


def _style_sheet(ws: Worksheet, money_cols: set[str]) -> None:
    headers = [c.value for c in ws[1]]
    for cell in ws[1]:
        cell.fill, cell.font = HEADER_FILL, HEADER_FONT
    for idx, header in enumerate(headers, start=1):
        letter = get_column_letter(idx)
        width = max(len(str(c.value or "")) for c in ws[letter])
        ws.column_dimensions[letter].width = min(max(width + 2, 12), 60)
        if header in money_cols:
            for cell in ws[letter][1:]:
                cell.number_format = MONEY_FORMAT
    ws.freeze_panes = "A2"


def build_fd_report(summary: dict, txns: pd.DataFrame, period: str) -> bytes:
    """Build an .xlsx workbook with interest summary, per-FD, monthly and transaction sheets."""
    money = {"Principal", "Gross Interest", "TDS", "Net Interest", "Principal Returned", "Amount"}
    sheets = {
        "Interest Summary": (_interest_summary_frame(summary, period), set()),
        "FD Summary": (_fd_summary_frame(summary), money),
        "Monthly": (_monthly_frame(summary), money),
        "Transactions": (_transactions_frame(txns), money),
    }
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, (frame, money_cols) in sheets.items():
            frame.to_excel(writer, sheet_name=name, index=False)
            _style_sheet(writer.sheets[name], money_cols)
        summary_ws = writer.sheets["Interest Summary"]
        for row in summary_ws.iter_rows(min_row=2):
            if isinstance(row[1].value, float) and "Rate" not in str(row[0].value):
                row[1].number_format = MONEY_FORMAT
        for cell in writer.sheets["FD Summary"][writer.sheets["FD Summary"].max_row]:
            cell.font = Font(bold=True)
    return buffer.getvalue()
