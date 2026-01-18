from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
import json
import os
import pathlib
import pandas as pd
import re
import csv
import sys
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_bank_analysis'  # Change in production

# Configuration Path
CONFIG_PATH = pathlib.Path("config.json")
CSV_PATH = pathlib.Path("files/easy_withdrawl.csv")

# ----------------------------------------------------------------------
# Logic extracted from main.py
# ----------------------------------------------------------------------
def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            c = json.load(f)
            # Ensure upper case mapping for matching
            c["party_mappings"] = {k.upper(): v for k, v in c.get("party_mappings", {}).items()}
            return c
    return {"directors": [], "employees": [], "party_mappings": {}}

def save_config(new_config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(new_config, f, indent=4)

def get_category_logic(narration, config):
    n = narration.upper()
    
    # 1. Configured Directors
    for d in config.get("directors", []):
        if d.upper() in n: return "Director Remuneration"

    # 2. Configured Employees
    for e in config.get("employees", []):
        if e.upper() in n: return "Employee Salary"
            
    # 3. Fallback keywords
    if any(x in n for x in ["SALARY", "PAYROLL", "JOB SALARY"]):
         if "DIRECTOR" in n: return "Director Remuneration"
         return "Employee Salary"
    
    if "DIRECTOR" in n: return "Director Remuneration"
    
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
    if any(x in n for x in ["POS TXN MARKUP", "POS DECCHG", "DC INTL POS TXN", "BANK CHARGES", "IMPS CHARGES", "ATM "]):
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
    
    if "CBDT" in n: return "Tax Payment (CBDT)"
    if "BAPS" in n or "DONATION" in n: return "Donation"

    return "Other / Uncategorized"

def get_party_logic(narration, config):
    nar = narration.upper()
    
    # 1. Configured Mappings
    mappings = config.get("party_mappings", {})
    sorted_keys = sorted(mappings.keys(), key=len, reverse=True)
    for key in sorted_keys:
        if key in nar:
            return mappings[key]
    
    # 2. FD / Financials
    if "FD THROUGH MOBILE" in nar or "FD BOOKED" in nar: return "FD Booking (HDFC)"
    if "TAX RECOVERY" in nar: return "Tax Recovery"
    if "FD INTEREST" in nar: return "FD Interest"
        
    # 3. Bank Charges
    if "POS TXN MARKUP" in nar or "POS DECCHG" in nar or "DC INTL POS TXN" in nar:
        return "Intl Transaction Markup/Charges"
    
    if "ATM " in nar or "ATM WDL" in nar or "DEBIT CARD" in nar:
        return "ATM / Debit Card Charges"
    
    # 4. Cleanup default
    clean = narration
    for prefix in ["NEFT DR-", "RTGS DR-", "IMPS-", "POS ", ".DC INTL ", "UPI-", "ME DC SI ", "CRV POS", "ME DC "]:
         clean = re.sub(r"^" + re.escape(prefix) + r"[A-Z0-9]*[\- ]*", "", clean, flags=re.I)
    clean = re.sub(r"^\d+[\- ]*", "", clean)
    clean = re.sub(r"^\d+X+\d+\s+", "", clean)
    return clean.strip()[:30]

def analyze_data():
    if not CSV_PATH.exists():
        return None
    
    config = load_config()
    
    rows = []
    with CSV_PATH.open("r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        for row in reader:
             if row and len(row) >= 1 and re.match(r"\d{2}/\d{2}/\d{2}", row[0]):
                 if len(row) >= 7:
                     rows.append(row[:7])
    
    cols = ["Date", "Narration", "Chq/Ref.No.", "Value Dt", "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"]
    df = pd.DataFrame(rows, columns=cols)
    
    for col in ["Withdrawal Amt.", "Deposit Amt.", "Closing Balance"]:
        df[col] = pd.to_numeric(df[col].replace("", "0"), errors="coerce").fillna(0)
    
    df = df[df["Withdrawal Amt."] > 0].copy()
    
    # Calculate Date Range / Financial Year
    try:
        # Convert Date column to datetime objects
        df["DateObj"] = pd.to_datetime(df["Date"], format="%d/%m/%y", errors="coerce")
        valid_dates = df["DateObj"].dropna()
        
        if not valid_dates.empty:
            min_date = valid_dates.min()
            max_date = valid_dates.max()
            
            # Logic for Financial Year (assuming Apr-Mar)
            # If start is Apr 2025, it's FY 2025-26
            fy_start_year = min_date.year if min_date.month >= 4 else min_date.year - 1
            fy_end_year = fy_start_year + 1
            
            # Check if all dates fall roughly within this FY
            # But user just wants "Financial analysis of year e.g. 2025-26"
            # We can label it based on the primary year range
            period_label = f"FY {fy_start_year}-{str(fy_end_year)[2:]}"
            
            # If dates span significantly more, maybe just show date range
            # But let's stick to the requested format "2025-26"
        else:
            period_label = "Unknown Period"
    except Exception as e:
        print(f"Date parsing error: {e}")
        period_label = "Unknown Period"

    df["Category"] = df["Narration"].apply(lambda n: get_category_logic(n, config))
    df["Party"] = df["Narration"].apply(lambda n: get_party_logic(n, config))
    
    total_withdrawn = df["Withdrawal Amt."].sum()
    
    cat_summary = df.groupby("Category")["Withdrawal Amt."].sum().reset_index().sort_values("Withdrawal Amt.", ascending=False)
    party_summary = df.groupby("Party")["Withdrawal Amt."].sum().reset_index().sort_values("Withdrawal Amt.", ascending=False)
    
    return {
        "period": period_label,
        "totals": {
            "withdrawn": str(total_withdrawn)
        },
        "category_breakdown": cat_summary.rename(columns={"Withdrawal Amt.": "Total"}).to_dict(orient="records"),
        "party_breakdown": party_summary.rename(columns={"Withdrawal Amt.": "Total"}).to_dict(orient="records")
    }

# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------

@app.route('/')
def index():
    # Dashboard is now public
    data = analyze_data()
    if data is None:
        return "Error: CSV file missing."
        
    return render_template('dashboard.html', 
                         data_json=json.dumps(data, indent=2),
                         logged_in=session.get('logged_in'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form['username'] == 'admin' and request.form['password'] == 'admin':
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        else:
            error = 'Invalid Credentials. Please try again.'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    data = analyze_data()
    if data is None:
        return "Error: CSV file missing."
        
    return render_template('dashboard.html', data_json=json.dumps(data, indent=2))

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    config = load_config()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'upload_file':
            if 'statement_file' not in request.files:
                flash('No file part', 'error')
                return redirect(url_for('admin'))
            file = request.files['statement_file']
            if file.filename == '':
                flash('No selected file', 'error')
                return redirect(url_for('admin'))
            if file and file.filename.endswith('.csv'):
                # Overwrite existing file
                file.save(CSV_PATH)
                flash('New statement uploaded successfully!', 'success')
                return redirect(url_for('index'))
            else:
                flash('Invalid file type. Please upload a CSV.', 'error')
                return redirect(url_for('admin'))

        elif action == 'add_director':
            val = request.form.get('director_name')
            if val and val not in config['directors']:
                config['directors'].append(val)
        
        elif action == 'remove_director':
            val = request.form.get('director_name')
            if val in config['directors']:
                config['directors'].remove(val)
                
        elif action == 'add_employee':
            val = request.form.get('employee_name')
            if val and val not in config['employees']:
                config['employees'].append(val)
        
        elif action == 'remove_employee':
            val = request.form.get('employee_name')
            if val in config['employees']:
                config['employees'].remove(val)
                
        elif action == 'add_mapping':
            key = request.form.get('mapping_key')
            val = request.form.get('mapping_val')
            if key and val:
                # Ensure we update the dictionary properly
                if "party_mappings" not in config: config["party_mappings"] = {}
                config["party_mappings"][key.upper()] = val
        
        elif action == 'remove_mapping':
            key = request.form.get('mapping_key')
            if key in config['party_mappings']:
                del config['party_mappings'][key]
                
        save_config(config)
        return redirect(url_for('admin'))
        
    return render_template('admin.html', config=config)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
