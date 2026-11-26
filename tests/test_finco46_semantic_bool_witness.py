"""FINCO46 PR #488 Correction A: witnesses for the boolean-aware semantic snapshot comparison.

`_semantic` (tests/test_fin_val_b2_c1_recovery_finite_opex.py) accepts only the representation change the first Save
makes (seeded Python bool -> its text form), with the same token contract as app.input_adapter._snapshot_bool_strict.
These witnesses prove a REAL boolean change, unset-vs-false, unknown tokens and cross-type collisions are still caught,
and that an authorised CAPEX recovery keeps CO2 explicitly disabled with a zero price through persisted and typed input.
Synthetic data only; no production code or financial engine involved.
"""
from __future__ import annotations

import copy

import pytest

from app.input_adapter import _snapshot_bool_strict
from tests.test_fin_val_b2_c1_recovery_finite_opex import (  # noqa: F401  (shared fixture + helpers)
    _history_count, _poison, _prime, _recovery_form, _semantic, _snapshot, env,
)


@pytest.fixture(autouse=True)
def _finco47_legacy_ssr_rollback(monkeypatch):
    """Scoped to this legacy SSR test module; default production flag stays React ON."""
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")

KEY = "rev_co2_enabled"


@pytest.mark.parametrize("raw,expected", [(False, False), ("False", False), ("false", False), (" FALSE ", False),
                                          ("0", False), ("no", False), (True, True), ("True", True), ("true", True),
                                          ("1", True), ("yes", True)])
def test_accepted_tokens_match_the_strict_adapter(raw, expected):
    assert _snapshot_bool_strict({KEY: raw}, KEY) is expected        # the production contract the helper mirrors
    assert _semantic({KEY: raw}) == {KEY: ("BOOL", expected)}


@pytest.mark.parametrize("a,b", [(False, "False"), (False, "false"), (True, "True"), (True, "true"), ("0", False)])
def test_representation_changes_are_equal(a, b):
    assert _semantic({KEY: a}) == _semantic({KEY: b})


@pytest.mark.parametrize("a,b", [(False, "True"), (True, "False"), ("false", "true"), (False, None), (False, ""),
                                 (None, True)])
def test_real_changes_and_unset_vs_false_stay_different(a, b):
    assert _semantic({KEY: a}) != _semantic({KEY: b})


@pytest.mark.parametrize("bad", ["off", "maybe", "Falsey", "2", "nan"])
def test_an_unknown_token_fails_loudly_and_is_never_read_as_false(bad):
    with pytest.raises(AssertionError, match="not a valid snapshot boolean"):
        _semantic({KEY: bad})


def test_no_cross_type_collision_and_other_fields_are_not_reinterpreted():
    # a bool field never equals the numeric 0 of an ordinary field (Python's False == 0 is not reused)
    assert _semantic({KEY: False})[KEY] != _semantic({"x": 0})["x"]
    # the literal text 'False' in a non-BOOL field stays text; numeric zero / empty / text remain distinct there
    assert _semantic({"project_name": "False"}) == {"project_name": "False"}
    assert len({repr(_semantic({"v": v})["v"]) for v in (0, "", "False")}) == 3


def test_negative_mutation_false_to_true_is_detected_on_the_real_recovery_snapshot(env):
    record = env.create()
    _prime(env, record)
    _poison(env, record, "capex_epc_contract_keur", "-20000.0")
    before = _snapshot(record)
    assert _snapshot_bool_strict(before, KEY) is False
    mutated = copy.deepcopy(before)            # disposable copy only: the real DB is never touched
    mutated[KEY] = "True"
    ignore = ("capex_epc_contract_keur",)
    assert _semantic(mutated, ignore=ignore) != _semantic(before, ignore=ignore)


def test_recovery_keeps_co2_false_and_zero_price_through_persisted_and_typed_input(env):
    from app.input_adapter import build_projectinputs_from_snapshot
    record = env.create()
    _prime(env, record)
    _poison(env, record, KEY, False)                       # explicit seeded false (bool) ...
    _poison(env, record, "rev_co2_price_eur_mwh", 0.0)     # ... and an explicit zero price, kept by the GET (FINCO46)
    _poison(env, record, "capex_epc_contract_keur", "-20000.0")
    form = _recovery_form(env.client.get("/v2/workbook", params={"project": record.project_code}).text)
    resp = env.client.post("/v2/workbook/update", data={**form, "value": "20000"}, follow_redirects=False)
    assert resp.status_code == 303 and "v2_err" not in resp.headers["location"]
    after = _snapshot(record)
    assert _snapshot_bool_strict(after, KEY) is False
    assert float(after["rev_co2_price_eur_mwh"]) == 0.0
    typed = build_projectinputs_from_snapshot(after)
    assert typed.revenue.co2_enabled is False and float(typed.revenue.co2_certificate_price_eur_per_mwh) == 0.0
    assert _history_count(env, record) == 0                # recovery never runs the model or writes history
