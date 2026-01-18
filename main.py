#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
easy_withdrawl_analysis.py
-------------------------
Read the CSV you supplied, separate salary‑payments from
all other out‑flows (vendors), and produce two summary tables:
    • Salary paid per employee
    • Vendor payments per merchant
"""

import pathlib
import re
import sys
import csv
import json
import webbrowser
import pandas as pd
import os

# ----------------------------------------------------------------------
# 1️⃣  Load & clean the CSV
# ----------------------------------------------------------------------
if len(sys.argv) > 1:
    CSV_PATH = pathlib.Path(sys.argv[1])
else:
    print("Warning: No CSV file specified, defaulting to 'easy_withdrawl.csv'")
    CSV_PATH = pathlib.Path("easy_withdrawl.csv")

# Use csv module to handle quoted fields correctly
rows = []
with CSV_PATH.open("r", encoding="utf-8", errors="replace") as f:
    reader = csv.reader(f)
    for row in reader:
        # Check if the first column looks like a date
        if row and len(row) >= 1 and re.match(r"\d{2}/\d{2}/\d{2}", row[0]):
             # Ensure we have the right number of columns (7)
             # If more, truncate. If less, pad? The files seem compliant if read correctly.
             if len(row) >= 7:
                 rows.append(row[:7])

# Build a DataFrame
cols = ["Date", "Narration", "Chq/Ref.No.", "Value Dt",
        "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"]
df = pd.DataFrame(rows, columns=cols)

# Convert the amount columns to numbers (empty strings → 0)
for col in ["Withdrawal Amt.", "Deposit Amt.", "Closing Balance"]:
    df[col] = pd.to_numeric(df[col].replace("", "0"), errors="coerce").fillna(0)

# Keep only rows where money actually left the account
df = df[df["Withdrawal Amt."] > 0].copy()

# ----------------------------------------------------------------------
# 2️⃣  Load Configuration & Categorization Logic
# ----------------------------------------------------------------------
CONFIG = {
    "directors": [],
    "employees": [],
    "party_mappings": {}
}

try:
    with open("config.json", "r", encoding="utf-8") as f:
        CONFIG = json.load(f)
        # Normalize keys in mapping to upper case for easier matching
        CONFIG["party_mappings"] = {k.upper(): v for k, v in CONFIG["party_mappings"].items()}
        print(f"Loaded config: {len(CONFIG['directors'])} directors, {len(CONFIG['employees'])} employees.")
except FileNotFoundError:
    print("⚠️ config.json not found. Using defaults.")

def get_category(narration: str) -> str:
    n = narration.upper()
    
    # 1. Check configured Directors
    for d in CONFIG["directors"]:
        if d.upper() in n:
            return "Director Remuneration"

    # 2. Check configured Employees
    for e in CONFIG["employees"]:
        if e.upper() in n:
            return "Employee Salary"
            
    # 3. Fallback keywords for Salary/Director if not in list
    if any(x in n for x in ["SALARY", "PAYROLL", "JOB SALARY"]):
         if "DIRECTOR" in n: return "Director Remuneration"
         return "Employee Salary"
    
    if "DIRECTOR" in n:
        return "Director Remuneration"
    
    # 4. Business Travel
    if any(x in n for x in ["FLIXBUS", "DB VERTRIEB", "FLIX", "MAKEMYTRIP", "LUFTHANSA", "EMIRATES", 
                            "SWISS", "AIR TRAVEL", "BOOKING.COM", "RYANAIR", "HOTEL", "TROPICAL ISLAND", 
                            "UBER", "OLA", "IRCTC", "ETIHAD", "AIR"]):
         return "Business Travel Expense"

    # 5. Recurring Tech/Services
    if any(x in n for x in ["REPLIT", "GITHUB", "RENDER.COM", "MICROSOFT", "GOOGLE", "FIGMA", "OPENAI", 
                            "ZOHO", "NORD", "VPN", "CLOUDFLARE", "HEROKU", "AWS", "DIGITALOCEAN", "NAPKIN AI"]):
        return "Recurring Services"

    # 6. Professional Fees
    if any(x in n for x in ["PROFESSIONAL FEE", "PROF FEES"]):
        return "Professional Fees"

    # 7. Bank Charges
    if any(x in n for x in ["POS TXN MARKUP", "POS DECCHG", "DC INTL POS TXN", "BANK CHARGES", "IMPS CHARGES"]):
        return "Bank Charges"

    # 8. FD / Financial
    if any(x in n for x in ["FD THROUGH MOBILE", "FD BOOKED", "TAX RECOVERY", "FD INTEREST"]):
        return "Financial / FD"
        
    # 9. Vendor / Office / Others
    if any(x in n for x in ["RELIANCE RETAIL", "AMAZON", "APPLE.COM", "DEALZY", "CHOCOLADE", "ZALANDO", 
                            "GOTBAG", "OFFICE", "EXPENSE", "PETROLEUM"]):
        return "Office Expense"
        
    if any(x in n for x in ["META WORLDS", "VENDOR"]):
        return "Vendor Payment"
    
    if "CBDT" in n:
        return "Tax Payment (CBDT)"
        
    if "BAPS" in n or "DONATION" in n:
        return "Donation"

    return "Other / Uncategorized"

def get_party(row) -> str:
    """Extract a readable party name based on common patterns."""
    nar = row["Narration"].upper()
    
    # 1. Check Configured Mappings
    # We iterate through keys to see if they exist in the narration substring
    # This allows partial matching (e.g. "FLIX" matching "FLIXBUS")
    # Sort keys by length desc to match longest first (e.g. "GOOGLE CLOUD" before "GOOGLE")
    sorted_keys = sorted(CONFIG["party_mappings"].keys(), key=len, reverse=True)
    for key in sorted_keys:
        if key in nar:
            return CONFIG["party_mappings"][key]
    
    # 2. FD / Financials (Special cases not easily in simple mapping)
    if "FD THROUGH MOBILE" in nar or "FD BOOKED" in nar:
        return "FD Booking (HDFC)"
    if "TAX RECOVERY" in nar:
        return "Tax Recovery"
    if "FD INTEREST" in nar:
        return "FD Interest"
        
    # 3. Bank Charges
    if "POS TXN MARKUP" in nar or "POS DECCHG" in nar or "DC INTL POS TXN" in nar:
        return "Intl Transaction Markup/Charges"
    
    # 4. Default cleanup for others
    clean_nar = row["Narration"]

    for prefix in ["NEFT DR-", "RTGS DR-", "IMPS-", "POS ", ".DC INTL ", "UPI-", "ME DC SI ", "CRV POS", "ME DC "]:
        # Regex to match prefix + potential bank codes
        # e.g. NEFT DR-UBIN0901407-
        clean_nar = re.sub(r"^" + re.escape(prefix) + r"[A-Z0-9]*[\- ]*", "", clean_nar, flags=re.I)
        
    # Remove dates or IDs at start
    clean_nar = re.sub(r"^\d+[\- ]*", "", clean_nar)
    
    # If it's a POS transaction, often "POS <ID> <NAME>" -> we stripped POS, now strip ID
    clean_nar = re.sub(r"^\d+X+\d+\s+", "", clean_nar)
    
    return clean_nar.strip()[:30]

# Apply
df["Category"] = df["Narration"].apply(get_category)
df["Party"] = df.apply(get_party, axis=1)

# Summaries
category_summary = (
    df.groupby("Category")["Withdrawal Amt."]
    .sum()
    .reset_index()
    .rename(columns={"Withdrawal Amt.": "Total"})
    .sort_values("Total", ascending=False)
)

party_summary = (
    df.groupby("Party")["Withdrawal Amt."]
    .sum()
    .reset_index()
    .rename(columns={"Withdrawal Amt.": "Total"})
    .sort_values("Total", ascending=False)
)




# ----------------------------------------------------------------------
# 5️⃣  Print nice tables
# ----------------------------------------------------------------------
def pretty_print(df_, title, n=20):
    print("\n" + "=" * 80)
    print(title)
    print("-" * 80)
    if len(df_) > n:
        print(df_.head(n).to_string(index=False))
        print(f"... (showing top {n} of {len(df_)} rows – use .head()/.tail() for the rest)")
    else:
        print(df_.to_string(index=False))
    print("=" * 80 + "\n")


# Overall totals
total_withdrawn = df["Withdrawal Amt."].sum()

print("\n=== OVERALL SUMMARY ===")
print(f"Total amount withdrawn from the account  : {total_withdrawn:,.2f}")


# Detailed tables
# Detailed tables
pretty_print(category_summary, "� Expenses by Category", n=20)
pretty_print(party_summary, "👤 Expenses by Party", n=20)

# ----------------------------------------------------------------------
# 6️⃣  Generate Web Dashboard
# ----------------------------------------------------------------------
data_export = {
    "totals": {
        "withdrawn": str(total_withdrawn),
    },
    "category_breakdown": category_summary.to_dict(orient="records"),
    "party_breakdown": party_summary.to_dict(orient="records")
}

# Read template
try:
    template_path = pathlib.Path("dashboard_template.html")
    if template_path.exists():
        html_content = template_path.read_text(encoding="utf-8")
        
        # Inject data
        json_data = json.dumps(data_export, indent=2)
        final_html = html_content.replace("{{ DATA_JSON }}", json_data).replace("{{DATA_JSON}}", json_data)
        
        # Write output
        output_path = pathlib.Path("dashboard.html")
        output_path.write_text(final_html, encoding="utf-8")
        
        print(f"\n✨ Dashboard generated: {output_path.resolve()}")
        print("Opening in browser...")
        webbrowser.open(f"file://{output_path.resolve()}")
    else:
        print("\n⚠️  dashboard_template.html not found. Skipping web report generation.")
except Exception as e:
    print(f"\n⚠️  Error generating web report: {e}")

# salary_summary.to_csv("salary_summary.csv", index=False)
# vendor_summary.to_csv("vendor_summary.csv", index=False)
