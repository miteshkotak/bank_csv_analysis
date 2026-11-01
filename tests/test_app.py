import io
import json
import re

import pytest

import app as app_module
import statements

CSV_2425 = """Date,Narration,Chq./Ref.No.,Value Dt,Withdrawal Amt.,Deposit Amt.,Closing Balance
08/08/24,RTGS CR-FUENFWERKEN DESIGN AG,1,08/08/24,,1000000,1000000
01/09/24,NEFT DR-TANVIR KHAN-EU IN LOAN,2,01/09/24,100000,,900000
01/10/24,POS COSTCO WHOLESALE,3,01/10/24,20000,,880000
15/03/25,CBDT/BANK REFERENCE NO:K2507432053009/CIN NO:Y,4,15/03/25,100000,,780000
"""
CSV_2526 = CSV_2425.replace("/24,", "/25,").replace("/25,", "/26,", 2).replace("15/03/26", "15/03/26")


def _tax_data(html: bytes) -> dict:
    match = re.search(rb"window\.TAX_DATA = (\{.*?\});\n", html, re.DOTALL)
    return json.loads(match.group(1))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(statements, "STATEMENTS_DIR", tmp_path / "statements")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"directors": [], "employees": [], "party_mappings": {}}))
    monkeypatch.setattr(app_module, "CONFIG_PATH", config_path)
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        with c.session_transaction() as s:
            s["logged_in"] = True
        yield c


def _upload(client, content: str, name: str = "statement.csv"):
    return client.post("/admin", data={"action": "upload_file", "statement_file": (io.BytesIO(content.encode()), name)},
                       content_type="multipart/form-data")


def test_analyze_without_statement_shows_message(client):
    assert b"No bank statement uploaded yet" in client.get("/analyze").data


def test_upload_stores_per_year_and_redirects_to_that_year(client):
    response = _upload(client, CSV_2425)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/analyze?fy=2024-25")
    assert statements.available_fys() == ["2024-25"]


def test_upload_rejects_non_csv_and_empty_statements(client):
    _upload(client, CSV_2425, name="statement.xlsx")
    _upload(client, "no transactions here\n")
    assert statements.available_fys() == []


def test_analysis_uses_default_rules(client):
    _upload(client, CSV_2425)
    data = _tax_data(client.get("/analyze?fy=2024-25").data)
    assert data["income"]["business"] == pytest.approx(1000000)
    # Loan excluded by default rule; Costco still deductible until a rule is added
    assert data["expenses"]["deductible"] == pytest.approx(20000)
    assert data["credits"]["advance_tax"] == pytest.approx(100000)


def test_admin_rule_change_flows_into_analysis(client):
    _upload(client, CSV_2425)
    client.post("/admin", data={"action": "add_rule", "list": "non_deductible", "keyword": "costco", "reason": "Personal"})
    data = _tax_data(client.get("/analyze?fy=2024-25").data)
    assert data["expenses"]["deductible"] == 0
    assert any(e["reason"] == "Personal" for e in data["expenses"]["excluded"])


def test_admin_invalid_rule_is_rejected_with_message(client):
    response = client.post("/admin", data={"action": "update_regime", "name": "x", "base_rate": "abc",
                                           "surcharge": "0", "cess": "4"}, follow_redirects=True)
    assert b"Base rate must be a number" in response.data


def test_admin_redirect_ignores_unsafe_anchor(client):
    response = client.post("/admin", data={"action": "set_challan", "ref": "K1", "kind": "auto",
                                           "anchor": "//evil.example"})
    assert response.headers["Location"].endswith("/admin")


def test_actuals_produce_reconciliation(client):
    _upload(client, CSV_2425)
    client.post("/admin", data={"action": "set_actuals", "fy": "2024-25", "advance_tax": "100000",
                                "self_assessment_tax": "120000", "self_assessment_paid_on": "2025-06-30"})
    data = _tax_data(client.get("/analyze?fy=2024-25").data)
    assert data["reconciliation"]["rows"][-1]["actual"] == pytest.approx(220000)


def test_admin_page_lists_challans_and_years(client):
    _upload(client, CSV_2425)
    html = client.get("/admin").data
    assert b"K2507432053009" in html
    assert b"FY 2024-25" in html


def test_fy_selector_and_report_follow_selected_year(client):
    _upload(client, CSV_2425)
    _upload(client, CSV_2526)
    assert statements.available_fys() == ["2025-26", "2024-25"]
    assert _tax_data(client.get("/analyze").data)["fy"] == "2025-26"
    assert _tax_data(client.get("/analyze?fy=2024-25").data)["fy"] == "2024-25"
    report = client.get("/analyze/fd-report.xlsx?fy=2024-25")
    assert "FY_2024-25" in report.headers["Content-Disposition"]
    assert client.get("/?fy=2024-25").status_code == 200
