import io
import json
import os
import pathlib
import re

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

import statements
from corporate_tax import compute_corporate_tax, list_challans
from fd_analysis import (
    FD_BOOKING,
    FD_INTEREST,
    FD_PRINCIPAL_RETURN,
    FD_TDS,
    classify_fd_txn,
    fd_transactions,
    summarize_fd,
)
from fd_report import build_fd_report
from tax_rules import TaxRuleError, apply_rule_action, get_tax_rules

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

    # 0. FD transactions (bank-generated narrations, checked first so keywords like "AIR" can't misfire)
    fd_type = classify_fd_txn(n)
    if fd_type: return fd_type

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
    fd_type = classify_fd_txn(nar)
    if fd_type == FD_BOOKING: return "FD Booking (HDFC)"
    if fd_type == FD_TDS: return "TDS on FD Interest"
    if fd_type == FD_INTEREST: return "FD Interest"
    if fd_type == FD_PRINCIPAL_RETURN: return "FD Principal Return"
        
    # 3. Bank Charges
    if "POS TXN MARKUP" in nar or "POS DECCHG" in nar or "DC INTL POS TXN" in nar:
        return "Intl Transaction Markup/Charges"
    
    if "ATM " in nar or "ATM WDL" in nar or "DEBIT CARD" in nar:
        return "ATM / Debit Card Charges"
    
    # 4. Cleanup default
    clean = narration
    for prefix in ["NEFT DR-", "RTGS DR-", "IMPS-", "POS ", ".DC INTL ", "UPI-", "ME DC SI ", "CRV POS", "ME DC "]:
         clean = re.sub(r"^" + re.escape(prefix) + r"[A-Z0-9]*[\- ]*", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"^\d+[\- ]*", "", clean)
    clean = re.sub(r"^\d+X+\d+\s+", "", clean)
    return clean.strip()[:30]

def load_statement(fy):
    """Load a financial year's statement as a categorised DataFrame, or None if not uploaded."""
    df = statements.load_raw(fy)
    if df is None:
        return None
    config = load_config()
    return df.assign(
        Category=df["Narration"].apply(lambda n: get_category_logic(n, config)),
        Party=df["Narration"].apply(lambda n: get_party_logic(n, config)),
    )

def selected_fy():
    """FY from ?fy=, falling back to the latest uploaded statement."""
    fys = statements.available_fys()
    requested = request.args.get("fy")
    if requested in fys:
        return requested
    return fys[0] if fys else None

def analyze_data(fy):
    df = load_statement(fy)
    if df is None:
        return None
    df = df[df["Withdrawal Amt."] > 0]

    total_withdrawn = df["Withdrawal Amt."].sum()
    
    cat_summary = df.groupby("Category")["Withdrawal Amt."].sum().reset_index().sort_values("Withdrawal Amt.", ascending=False)
    party_summary = df.groupby("Party")["Withdrawal Amt."].sum().reset_index().sort_values("Withdrawal Amt.", ascending=False)
    
    return {
        "period": statements.fy_label(fy),
        "fy": fy,
        "fys": statements.available_fys(),
        "totals": {
            "withdrawn": str(total_withdrawn)
        },
        "category_breakdown": cat_summary.rename(columns={"Withdrawal Amt.": "Total"}).to_dict(orient="records"),
        "party_breakdown": party_summary.rename(columns={"Withdrawal Amt.": "Total"}).to_dict(orient="records")
    }

NO_STATEMENT_MSG = "No bank statement uploaded yet. Log in and upload one from the Admin page."

# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------

@app.route('/')
def index():
    # Dashboard is now public
    data = analyze_data(selected_fy())
    if data is None:
        return NO_STATEMENT_MSG
        
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
    
    data = analyze_data(selected_fy())
    if data is None:
        return NO_STATEMENT_MSG
        
    return render_template('dashboard.html', data_json=json.dumps(data, indent=2))

def handle_upload():
    file = request.files.get('statement_file')
    if file is None or file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('admin'))
    if not file.filename.lower().endswith('.csv'):
        flash('Invalid file type. Please upload a CSV.', 'error')
        return redirect(url_for('admin'))
    try:
        fy = statements.save_statement(file.read())
    except statements.StatementError as e:
        flash(str(e), 'error')
        return redirect(url_for('admin'))
    flash(f'Statement for {statements.fy_label(fy)} uploaded. Tax analysis recalculated.', 'success')
    return redirect(url_for('analyze', fy=fy))

TAX_RULE_ACTIONS = {"add_rule", "update_rule", "remove_rule", "update_regime", "set_challan", "set_actuals"}

def handle_tax_rule_action(config, action):
    try:
        rules = apply_rule_action(get_tax_rules(config), action, request.form.to_dict())
    except TaxRuleError as e:
        flash(str(e), 'error')
        return
    save_config({**config, "tax_rules": rules})
    flash('Tax rules updated.', 'success')

def admin_challans(rules):
    """CBDT challans from every uploaded statement, with the year each is counted towards."""
    challans = []
    for fy in statements.available_fys():
        df = statements.load_raw(fy)
        challans += [{**c, "statement_fy": fy} for c in list_challans(df, fy, rules)]
    return sorted(challans, key=lambda c: c["date"], reverse=True)

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    config = load_config()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'upload_file':
            return handle_upload()

        if action in TAX_RULE_ACTIONS:
            handle_tax_rule_action(config, action)
            anchor = request.form.get('anchor', '')
            return redirect(url_for('admin') + (anchor if re.fullmatch(r"#[\w-]+", anchor) else ''))

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

    rules = get_tax_rules(config)
    fys = statements.available_fys()
    actual_years = sorted(set(fys) | set(rules["actuals"]), reverse=True)
    return render_template('admin.html', config=config, rules=rules, fys=fys,
                           challans=admin_challans(rules), actual_years=actual_years)

def calculate_tax_analysis(fy):
    """Corporate tax estimate for a financial year, using the editable rules from Admin."""
    df = load_statement(fy)
    if df is None:
        return None
    rules = get_tax_rules(load_config())
    return {
        **compute_corporate_tax(df, rules, fy),
        "period": statements.fy_label(fy),
        "fys": statements.available_fys(),
        "fd_summary": summarize_fd(df),
    }

@app.route('/analyze')
def analyze():
    tax_data = calculate_tax_analysis(selected_fy())
    if tax_data is None:
        return NO_STATEMENT_MSG
    
    return render_template('analyze.html', 
                         tax_data=json.dumps(tax_data, indent=2),
                         logged_in=session.get('logged_in'))

@app.route('/analyze/fd-report.xlsx')
def fd_report():
    fy = selected_fy()
    df = load_statement(fy) if fy else None
    if df is None:
        return NO_STATEMENT_MSG, 404
    period_label = statements.fy_label(fy)

    report = build_fd_report(summarize_fd(df), fd_transactions(df), period=period_label)
    filename = f"FD_Interest_Report_{period_label.replace(' ', '_')}.xlsx"
    return send_file(
        io.BytesIO(report),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )

# Move the old single statement file into per-year storage on first run
statements.migrate_legacy(CSV_PATH)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8000'))
    app.run(host='0.0.0.0', port=port, debug=True)
