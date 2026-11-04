"""G7: a NEW CAPEX/OPEX line must state its amount: required, finite, zero-or-greater (explicit 0 allowed); a missing value is never read as 0.

Synthetic disposable data only. Every refusal is a typed 422 and is proven by an unchanged composite identity AND unchanged rows.
"""
from __future__ import annotations

import pytest

from tests.model_mutation_csrf import post_valid_mutation
from tests.test_model_react_wf2_projections_v1 import env, costlines, cas  # noqa: F401  (shared real-app fixture)


def _state(env, record, sheet):
    p = costlines(env, record, sheet)
    return p["save"]["content_hash"], [(l["sub_line_id"], l["active"], l["amount_keur"], l["row_version"]) for l in p["lines"]]


def _post(env, record, sheet, label, **amount):
    before = costlines(env, record, sheet)
    group = before["line_management"]["eligible_groups"][0]
    field = before["line_management"]["add"]["group_field"]
    data = {"project": record.project_code, field: group["code"], "label": label, "notes": "", **cas(before), **amount}
    if sheet == "opex":
        data["inflation_pct"] = "0"
    return post_valid_mutation(env.client, f"/v2/{sheet}/line/add", data=data, follow_redirects=False)


BAD = {
    "missing": {},
    "blank": {"amount_keur": ""},
    "whitespace": {"amount_keur": "   "},
    "negative": {"amount_keur": "-1"},
    "tiny_negative": {"amount_keur": "-0.0001"},
    "nan": {"amount_keur": "nan"},
    "inf": {"amount_keur": "inf"},
    "minus_inf": {"amount_keur": "-inf"},
    "text": {"amount_keur": "12abc"},
    "overflow": {"amount_keur": "1e999"},
    "unicode_digits": {"amount_keur": "١٢"},
}


@pytest.mark.parametrize("sheet", ["capex", "opex"])
@pytest.mark.parametrize("case", sorted(BAD))
def test_a_bad_new_line_amount_is_a_typed_422_and_changes_nothing(env, sheet, case):
    record = env.create("solar")
    before = _state(env, record, sheet)
    r = _post(env, record, sheet, "G7 bad " + case, **BAD[case])
    assert r.status_code == 422, (case, r.status_code, r.text[:200])
    assert "error" in r.json() and "Amount (kEUR)" in r.json()["error"]
    assert _state(env, record, sheet) == before


@pytest.mark.parametrize("sheet", ["capex", "opex"])
def test_explicit_zero_and_a_precise_positive_amount_are_accepted_exactly(env, sheet):
    record = env.create("wind")
    assert _post(env, record, sheet, "G7 zero", amount_keur="0").status_code == 303
    assert _post(env, record, sheet, "G7 precise", amount_keur="1234.567891").status_code == 303
    lines = {l["label"]: l["amount_keur"] for l in costlines(env, record, sheet)["lines"]}
    assert float(lines["G7 zero"]) == 0.0 and float(lines["G7 precise"]) == 1234.567891      # no rounding of kEUR precision


@pytest.mark.parametrize("sheet", ["capex", "opex"])
def test_an_update_of_an_existing_line_keeps_its_unchanged_finite_only_rule(env, sheet):
    record = env.create("solar")
    assert _post(env, record, sheet, "G7 existing", amount_keur="5").status_code == 303
    p = costlines(env, record, sheet)
    line = next(l for l in p["lines"] if l["label"] == "G7 existing")
    data = {"project": record.project_code, "sub_line_id": line["sub_line_id"], "label": "G7 existing", "amount_keur": "nan",
            "notes": "", "row_version": line["row_version"], **cas(p)}
    if sheet == "opex":
        data["inflation_pct"] = "0"
    r = post_valid_mutation(env.client, f"/v2/{sheet}/line/update", data=data, follow_redirects=False)
    assert r.status_code == 422                                                              # non-finite is still refused on update (unchanged)
