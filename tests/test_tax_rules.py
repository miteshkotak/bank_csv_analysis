import pytest

from tax_rules import (
    DEFAULT_TAX_RULES,
    TaxRuleError,
    apply_rule_action,
    effective_rate,
    get_tax_rules,
    match_rule,
)


def test_defaults_used_when_config_has_no_rules():
    rules = get_tax_rules({})
    assert rules["regime"]["base_rate"] == 22.0
    assert any(r["keyword"] == "LOAN" for r in rules["non_deductible"])


def test_config_lists_replace_defaults_so_removals_stick():
    rules = get_tax_rules({"tax_rules": {"non_deductible": []}})
    assert rules["non_deductible"] == []
    assert rules["non_income"] == DEFAULT_TAX_RULES["non_income"]


def test_get_tax_rules_does_not_mutate_defaults():
    rules = get_tax_rules({})
    rules["non_deductible"].append({"keyword": "X", "reason": "y"})
    assert not any(r["keyword"] == "X" for r in DEFAULT_TAX_RULES["non_deductible"])


def test_effective_rate_115baa():
    assert effective_rate({"base_rate": 22, "surcharge": 10, "cess": 4}) == pytest.approx(25.168)


def test_match_rule_case_insensitive():
    rules = [{"keyword": "loan", "reason": "Loan given"}]
    assert match_rule("NEFT DR-SBIN-TANVIR KHAN-EU IN LOAN", rules)["reason"] == "Loan given"
    assert match_rule("SALARY", rules) is None


def _rules():
    return get_tax_rules({})


def test_add_update_remove_rule():
    rules = apply_rule_action(_rules(), "add_rule", {"list": "non_deductible", "keyword": "costco", "reason": "Personal"})
    assert {"keyword": "COSTCO", "reason": "Personal"} in rules["non_deductible"]

    rules = apply_rule_action(rules, "update_rule", {
        "list": "non_deductible", "original_keyword": "COSTCO", "keyword": "COSTCO WHOLESALE", "reason": "Personal spend"})
    assert {"keyword": "COSTCO WHOLESALE", "reason": "Personal spend"} in rules["non_deductible"]
    assert not any(r["keyword"] == "COSTCO" for r in rules["non_deductible"])

    rules = apply_rule_action(rules, "remove_rule", {"list": "non_deductible", "keyword": "COSTCO WHOLESALE"})
    assert not any(r["keyword"].startswith("COSTCO") for r in rules["non_deductible"])


def test_add_rule_rejects_duplicates_and_unknown_lists():
    with pytest.raises(TaxRuleError):
        apply_rule_action(_rules(), "add_rule", {"list": "non_deductible", "keyword": "LOAN", "reason": "dup"})
    with pytest.raises(TaxRuleError):
        apply_rule_action(_rules(), "add_rule", {"list": "bogus", "keyword": "X", "reason": "y"})
    with pytest.raises(TaxRuleError):
        apply_rule_action(_rules(), "add_rule", {"list": "non_income", "keyword": "  ", "reason": "y"})


def test_update_regime_validates_percentages():
    rules = apply_rule_action(_rules(), "update_regime", {"name": "Old regime", "base_rate": "25", "surcharge": "0", "cess": "4"})
    assert rules["regime"] == {"name": "Old regime", "base_rate": 25.0, "surcharge": 0.0, "cess": 4.0}
    with pytest.raises(TaxRuleError):
        apply_rule_action(_rules(), "update_regime", {"name": "x", "base_rate": "abc", "surcharge": "0", "cess": "4"})
    with pytest.raises(TaxRuleError):
        apply_rule_action(_rules(), "update_regime", {"name": "x", "base_rate": "150", "surcharge": "0", "cess": "4"})


def test_set_and_reset_challan():
    rules = apply_rule_action(_rules(), "set_challan", {"ref": "K123", "ay": "2024-25", "kind": "self_assessment"})
    assert rules["tax_payments"]["K123"] == {"ay": "2024-25", "kind": "self_assessment"}
    rules = apply_rule_action(rules, "set_challan", {"ref": "K123", "ay": "", "kind": "auto"})
    assert "K123" not in rules["tax_payments"]
    with pytest.raises(TaxRuleError):
        apply_rule_action(_rules(), "set_challan", {"ref": "K1", "ay": "24-25", "kind": "advance"})


def test_set_actuals_parses_numbers_and_skips_blanks():
    rules = apply_rule_action(_rules(), "set_actuals", {
        "fy": "2024-25", "advance_tax": "3,50,000", "self_assessment_tax": "181560",
        "self_assessment_paid_on": "2025-06-30", "total_income": "", "net_tax": "", "interest": "", "taxes_paid": ""})
    assert rules["actuals"]["2024-25"] == {
        "advance_tax": 350000.0, "self_assessment_tax": 181560.0, "self_assessment_paid_on": "2025-06-30"}
    with pytest.raises(TaxRuleError):
        apply_rule_action(_rules(), "set_actuals", {"fy": "2024-25", "advance_tax": "lots"})
    with pytest.raises(TaxRuleError):
        apply_rule_action(_rules(), "set_actuals", {"fy": "2024-25", "self_assessment_paid_on": "30/06/2025"})
