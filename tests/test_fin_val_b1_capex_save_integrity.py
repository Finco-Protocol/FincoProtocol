"""FIN-VAL B1 — CAPEX Save integrity (SC-2) and precision-safe display allocation (SC-4).

Scope: the 14 editable BOUND ``capex.C.*`` / ``capex.D.*`` amount fields get ``min_value=0`` (the canonical
adapter already rejects negatives), and ``allocate_parent_amount`` stops failing on finite amounts only because
of the default 28-digit Decimal context.  No economic maximum, no solver, Run or router change.  All persistence
checks use disposable databases and the real canonical routes/fixtures.
"""
from __future__ import annotations

import decimal
import json
import math
import random
import re
import sqlite3
from decimal import Decimal, ROUND_HALF_UP
from types import SimpleNamespace

import pytest

from app.input_adapter import _SCALAR_CAPEX_MAP, SnapshotInputError, build_projectinputs_from_snapshot
from app.reference_detail_catalog import (
    NonFiniteParentAmountError, allocate_parent_amount, capex_children, opex_children,
)
from app.workbook.registry import WORKBOOK
from app.workbook.update_service import WorkbookUpdateService

USER = "fin-val-b1-user"
CAPEX_FIELDS = sorted(
    f.field_id for f in WORKBOOK.all_fields()
    if f.field_id.startswith("capex.") and f.editable and f.binding_status.name == "BOUND"
)


# ── fixtures ────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def env(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence import db
    from app.runtime.model_execution import reset_model_executor_for_tests
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.v2.grid_router import router as grid_router
    from app.v2.router import router

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "finval.db"))
    db.init_db()
    app = FastAPI()
    app.include_router(router, prefix="/v2")
    app.include_router(grid_router, prefix="/v2")
    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=USER, username="admin"))

        def create(kind="solar", capacity=16, name=None):
            return create_reference_seeded_project(
                user_id=USER, requested_name=name or "FinVal " + kind,
                template_source="generic_" + kind + "_reference", capacity_mw=capacity)

        yield SimpleNamespace(client=client, create=create, db_path=str(tmp_path / "finval.db"), app=app)
    reset_model_executor_for_tests()


def _ws(record):
    from app.persistence.workspace_repository import get_workspace_state
    return get_workspace_state(USER, record.project_id)


def _page_tokens(env, record):
    """Tokens exactly as the server renders them for this session and project.

    * ``grid_csrf``    - ``data-csrf`` of the rendered input grid (the grid-save token of whichever contract
                         the server is running: plain signed token on current main, operation-bound
                         ``grid-save`` token under the SEC-02 mutation contract).
    * ``update_csrf``  - the hidden ``csrf_token`` of a rendered ``/v2/workbook/update`` field form
                         (``workbook-update`` operation token under SEC-02; absent on current main, where
                         that route carries no token and the key is simply not sent).
    Nothing is minted by the test; no unpublished security module is imported.
    """
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    assert page.status_code == 200
    out = {k: re.search(f'name="{k}" value="([^"]*)"', page.text).group(1) for k in ("content_hash", "workbook_version")}
    grid = re.search(r'id="v2-input-grid"[^>]*', page.text)
    assert grid is not None
    attrs = grid.group(0)
    out["grid_csrf"] = re.search(r'data-csrf="([^"]*)"', attrs).group(1)
    out["grid_hash"] = re.search(r'data-content-hash="([^"]*)"', attrs).group(1)
    form = re.search(r'hx-post="/v2/workbook/update"[^>]*>\s*<input type="hidden" name="csrf_token" value="([^"]*)"', page.text)
    out["update_csrf"] = form.group(1) if form else ""
    return out


def _refresh_cas(tokens, record):
    """Replace only the compare-and-swap identity (not any CSRF token) with the server's current composite hash.

    Used when the workbook page itself is not renderable (unreadable legacy draft) so tokens were captured from
    the rendered page BEFORE the draft was damaged.
    """
    from app.workbook.workbook_identity import assemble_consistent_for_get
    h = assemble_consistent_for_get(USER, record.project_id, WORKBOOK.version).composite_hash
    return {**tokens, "content_hash": h, "grid_hash": h, "workbook_version": WORKBOOK.version}


def _single_save(env, record, field_id, value, tokens=None):
    t = tokens or _page_tokens(env, record)
    data = {"project": record.project_code, "field_id": field_id, "value": value,
            "content_hash": t["content_hash"], "workbook_version": t["workbook_version"]}
    if t.get("update_csrf"):
        data["csrf_token"] = t["update_csrf"]
    return env.client.post("/v2/workbook/update", headers={"HX-Request": "true"}, data=data)


def _grid_save(env, record, cells, tokens=None, **over):
    t = tokens or _page_tokens(env, record)
    body = {"project": record.project_code, "csrf_token": t["grid_csrf"], "content_hash": t["grid_hash"],
            "workbook_version": t["workbook_version"], "scenario_id": None, "cells": cells}
    body.update(over)
    return env.client.post("/v2/workbook/grid/save", json=body)


def _snapshot(record):
    return dict(_ws(record).draft_snapshot)


def _key(field_id):
    return WORKBOOK.field(field_id).snapshot_key


# ── SC-2: registry / adapter alignment ──────────────────────────────────────────────────────────────
def test_exactly_the_fourteen_adapter_capex_fields_carry_min_zero():
    assert len(CAPEX_FIELDS) == 14
    specs = [WORKBOOK.field(f) for f in CAPEX_FIELDS]
    assert {s.snapshot_key for s in specs} == set(_SCALAR_CAPEX_MAP)
    assert all(s.min_value == 0 and s.max_value is None for s in specs)      # no economic maximum introduced
    others = [f for f in WORKBOOK.all_fields() if f.field_id.startswith("capex.") and f.field_id not in CAPEX_FIELDS]
    assert others and all(f.min_value is None and f.max_value is None for f in others)   # derived/locked rows untouched


def test_other_registry_numeric_bounds_unchanged():
    expected = {
        "revenue.ppa.base_tariff": (0, None), "project_setup.technical.capacity_mw": (0.1, None),
        "project_setup.technical.p50_hours": (1, None), "debt.senior.gearing_pct": (0, 100),
        "debt.senior.interest_rate_pct": (0, 20), "debt.senior.target_dscr": (1.0, 3.0),
        # B2/C1 (E-class): the 11 editable OPEX line amounts now carry min 0 like the adapter/engine (asserted in
        # tests/test_fin_val_b2_c1_recovery_finite_opex.py); every other bound listed here is unchanged.
        "opex.lines.om_preventive": (0, None), "tax.assumptions.cit_rate_pct": (0, 100),
    }
    for field_id, bounds in expected.items():
        spec = WORKBOOK.field(field_id)
        assert (spec.min_value, spec.max_value) == bounds, field_id


@pytest.mark.parametrize("field_id", CAPEX_FIELDS)
def test_adapter_rejects_negative_for_every_registry_field(env, field_id):
    """Independent per-field verification of the contract being mirrored (adapter side)."""
    record = env.create()
    snap = _snapshot(record)
    snap[_key(field_id)] = "-1"
    with pytest.raises(SnapshotInputError):
        build_projectinputs_from_snapshot(snap)
    snap[_key(field_id)] = "0"
    build_projectinputs_from_snapshot(snap)                                   # zero is a supported value


@pytest.mark.parametrize("field_id", CAPEX_FIELDS)
def test_validation_rejects_negative_zero_and_positive_are_valid(field_id):
    bad = WorkbookUpdateService.validate_field_update(field_id, "-1")
    assert not bad.is_valid and bad.error_class.value == "OUT_OF_BOUNDS" and "≥ 0" in bad.error
    for raw in ("0", "0.0", "1", "20000", "1234567.89"):
        assert WorkbookUpdateService.validate_field_update(field_id, raw).is_valid, (field_id, raw)
    for raw in ("nan", "inf", "-inf", "1e309", "abc"):
        assert not WorkbookUpdateService.validate_field_update(field_id, raw).is_valid, (field_id, raw)


@pytest.mark.parametrize("field_id", CAPEX_FIELDS)
def test_single_save_refuses_negative_and_changes_nothing(env, field_id):
    record = env.create()
    tokens = _page_tokens(env, record)
    before = _snapshot(record)
    response = _single_save(env, record, field_id, "-20000", tokens)
    assert response.status_code == 200 and "≥ 0" in response.text           # typed bounds message, HTMX 200 contract
    assert _snapshot(record) == before                                      # nothing persisted
    assert env.client.get("/v2/workbook", params={"project": record.project_code}).status_code == 200


@pytest.mark.parametrize("field_id", CAPEX_FIELDS)
def test_grid_save_refuses_negative_atomically(env, field_id):
    record = env.create()
    tokens = _page_tokens(env, record)
    before = _snapshot(record)
    cells = [{"field_id": "revenue.ppa.base_tariff", "value": "55"}, {"field_id": field_id, "value": "-1"}]
    response = _grid_save(env, record, cells, tokens)
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "GRID_VALIDATION_FAILED"
    verdicts = {c["field_id"]: c for c in body["cells"]}
    assert verdicts[field_id]["ok"] is False and verdicts[field_id]["error_class"] == "OUT_OF_BOUNDS"
    assert verdicts["revenue.ppa.base_tariff"]["ok"] is True
    after = _snapshot(record)
    assert after == before and after.get("rev_ppa_base_tariff") == before.get("rev_ppa_base_tariff")   # valid sibling NOT committed
    assert _page_tokens(env, record)["grid_hash"] == tokens["grid_hash"]


def test_zero_and_positive_capex_remain_savable_and_effective_values_match(env):
    # (a) zero stays valid through both routes, on a project whose page renders between the Saves
    record = env.create(name="FinVal zero")
    assert _single_save(env, record, "capex.C.epc_contract", "0").status_code == 200
    assert float(_snapshot(record)["capex_epc_contract_keur"]) == 0.0
    r1 = _grid_save(env, record, [{"field_id": "capex.C.insurances", "value": "0"}])
    assert r1.status_code == 200 and float(_snapshot(record)["capex_insurances_keur"]) == 0.0
    assert build_projectinputs_from_snapshot(_snapshot(record)).capex.insurances.amount_keur == 0.0
    # (b) all 14 positive amounts in ONE atomic grid Save (tokens rendered before; the page is not needed afterwards)
    record = env.create(name="FinVal positive")
    base_inputs = build_projectinputs_from_snapshot(_snapshot(record))
    values = {f: str(1000 + 10 * i) for i, f in enumerate(CAPEX_FIELDS)}
    response = _grid_save(env, record, [{"field_id": f, "value": v} for f, v in values.items()])
    assert response.status_code == 200 and response.json()["ok"] is True
    snap = _snapshot(record)
    effective = build_projectinputs_from_snapshot(snap)
    for field_id, raw in values.items():
        assert float(snap[_key(field_id)]) == float(raw)
        attr = _SCALAR_CAPEX_MAP[_key(field_id)]
        assert getattr(effective.capex, attr).amount_keur == pytest.approx(float(raw))
    assert effective.revenue.ppa_base_tariff == base_inputs.revenue.ppa_base_tariff     # unrelated inputs unchanged


def test_resaving_the_current_positive_value_is_an_effective_noop(env):
    record = env.create()
    seed = [{"field_id": "capex.C.epc_contract", "value": "21000"}, {"field_id": "capex.C.grid_connection", "value": "2500.5"}]
    assert _grid_save(env, record, seed).status_code == 200
    before_inputs = build_projectinputs_from_snapshot(_snapshot(record))
    snap = _snapshot(record)
    again = [{"field_id": c["field_id"], "value": str(snap[_key(c["field_id"])])} for c in seed]
    assert _grid_save(env, record, again).status_code == 200            # fresh rendered tokens and CAS identity
    assert build_projectinputs_from_snapshot(_snapshot(record)).capex == before_inputs.capex


def test_other_technologies_and_cost_line_authorities_unchanged(env):
    for kind in ("wind", "data_center", "ev_charging"):
        record = env.create(kind, name="FinVal " + kind)
        t = _page_tokens(env, record)
        bad = _single_save(env, record, "capex.C.epc_contract", "-5", t)
        assert "≥ 0" in bad.text
        assert env.client.get("/v2/workbook", params={"project": record.project_code}).status_code == 200
    # B2/C1 supersedes the B1 statement that negative OPEX stays accepted: the engine clamps negative OPEX to zero
    # (a silently ignored input), so the Save contract now refuses it.  See OPEX_FIELD_TO_ENGINE_AUTHORITY_MATRIX.md.
    assert not WorkbookUpdateService.validate_field_update("opex.lines.om_preventive", "-100").is_valid
    assert WorkbookUpdateService.validate_field_update("opex.lines.om_preventive", "0").is_valid


def test_stored_invalid_snapshot_is_not_rewritten_by_this_change(env):
    """Legacy unreadable drafts stay exactly as stored: reads, identity computation and an unrelated Save do not
    migrate, clean or reject-by-rewrite the stored negative value (no automatic repair in this PR)."""
    record = env.create()
    rendered = _page_tokens(env, record)          # authentic server-issued tokens, captured while the page still renders
    with sqlite3.connect(env.db_path) as conn:
        raw = conn.execute("SELECT draft_snapshot_json FROM workspace_states WHERE project_id=?", (record.project_id,)).fetchone()[0]
        snap = json.loads(raw)
        snap["capex_epc_contract_keur"] = "-20000.0"
        stored_json = json.dumps(snap)
        conn.execute("UPDATE workspace_states SET draft_snapshot_json=? WHERE project_id=?", (stored_json, record.project_id))
    assert _snapshot(record)["capex_epc_contract_keur"] == "-20000.0"
    assert _snapshot(record)["capex_epc_contract_keur"] == "-20000.0"           # reading never mutates the stored value
    # B2/C1 (SC-3): the unreadable draft is now answered by an explicit recovery page (HTTP 200, no 500); the stored
    # value is still not rewritten, cleaned or masked, and nothing is run.
    recovery = env.client.get("/v2/workbook", params={"project": record.project_code})
    assert recovery.status_code == 200 and 'data-testid="workbook-recovery-page"' in recovery.text
    assert _snapshot(record)["capex_epc_contract_keur"] == "-20000.0"
    # an unrelated, valid canonical Save still works and leaves the legacy negative value untouched
    response = _grid_save(env, record, [{"field_id": "revenue.ppa.base_tariff", "value": "51"}], _refresh_cas(rendered, record))
    assert response.status_code == 200
    after = _snapshot(record)
    assert after["capex_epc_contract_keur"] == "-20000.0"
    assert float(after["rev_ppa_base_tariff"]) == 51.0
    # saving the invalid field again is refused; the stored legacy value is still not rewritten
    refused = _grid_save(env, record, [{"field_id": "capex.C.epc_contract", "value": "-5"}], _refresh_cas(rendered, record))
    assert refused.status_code == 422
    assert _snapshot(record)["capex_epc_contract_keur"] == "-20000.0"
    # the explicit repair path remains a deliberate user Save of a valid value (no automatic rewrite happened before it)
    fixed = _grid_save(env, record, [{"field_id": "capex.C.epc_contract", "value": "20000"}], _refresh_cas(rendered, record))
    assert fixed.status_code == 200 and float(_snapshot(record)["capex_epc_contract_keur"]) == 20000.0
    assert env.client.get("/v2/workbook", params={"project": record.project_code}).status_code == 200


# ── CAS / CSRF / ownership unchanged ────────────────────────────────────────────────────────────────
def test_cas_csrf_ownership_and_scenario_guards_unchanged(env):
    record = env.create()
    t = _page_tokens(env, record)
    before = _snapshot(record)
    cells = [{"field_id": "capex.C.epc_contract", "value": "21000"}]
    # CSRF precedes validation, even for an invalid value
    bad = env.client.post("/v2/workbook/grid/save", json={
        "project": record.project_code, "csrf_token": "bad", "content_hash": t["grid_hash"],
        "workbook_version": t["workbook_version"], "scenario_id": None,
        "cells": [{"field_id": "capex.C.epc_contract", "value": "-1"}]})
    assert bad.status_code == 403 and bad.json()["code"] == "CSRF_INVALID"
    for missing in ({"csrf_token": ""}, {"csrf_token": None}):
        body = {"project": record.project_code, "content_hash": t["grid_hash"], "workbook_version": t["workbook_version"],
                "scenario_id": None, "cells": cells, **missing}
        assert env.client.post("/v2/workbook/grid/save", json=body).status_code in (403, 422)
    assert _snapshot(record) == before
    # stale CAS
    stale = _grid_save(env, record, cells, t, content_hash="0" * 64)
    assert stale.status_code == 409 and stale.json()["reload"] is True
    # workbook version mismatch
    assert _grid_save(env, record, cells, t, workbook_version="0.0.0").status_code == 409
    # scenario scope mismatch
    assert _grid_save(env, record, cells, t, scenario_id="no-such-scenario").status_code == 409
    # ownership / cross-session: another user replaying the owner's rendered token is denied and nothing is written.
    # Current main answers 404 (token is not session bound, ownership check refuses); the session-bound SEC-02
    # contract answers 403 CSRF_INVALID first.  Both deny before any persistence.
    from fastapi.testclient import TestClient
    from app.auth import COOKIE_NAME, create_session_token
    with TestClient(env.app, raise_server_exceptions=False) as other:
        other.cookies.set(COOKIE_NAME, create_session_token(user_id="someone-else", username="x"))
        r = other.post("/v2/workbook/grid/save", json={
            "project": record.project_code, "csrf_token": t["grid_csrf"], "content_hash": t["grid_hash"],
            "workbook_version": t["workbook_version"], "scenario_id": None, "cells": cells})
        assert r.status_code in (403, 404)
        assert _snapshot(record) == before
    # single-field stale hash is refused as before
    s = _single_save(env, record, "capex.C.epc_contract", "21000", {**t, "content_hash": "0" * 64})
    assert s.status_code == 200 and "changed" in s.text.lower()
    assert _snapshot(record) == before
    # and the valid write still works afterwards
    assert _grid_save(env, record, cells, t).status_code == 200


def test_forged_workbook_update_token_never_commits_once_the_server_enforces_it(env):
    """Negative token test for the single-field route.  Current main renders a ``csrf_token`` in the field form
    but does not validate it; the SEC-02 contract (operation-bound ``workbook-update`` token) does.  The test
    detects enforcement with a no-op probe (value equal to the stored one) and, only if the server enforces, asserts
    that forged/missing tokens are refused and write nothing.  It never claims enforcement the base lacks and
    never skips (the mandatory CI gate treats any non-pass as a failure)."""
    record = env.create()
    t = _page_tokens(env, record)
    before = _snapshot(record)
    current = str(before["rev_ppa_base_tariff"])               # stored value re-submitted: value-neutral probe
    probe = _single_save(env, record, "revenue.ppa.base_tariff", current, {**t, "update_csrf": "bad"})
    watched = (*_SCALAR_CAPEX_MAP, "rev_ppa_base_tariff")
    before_values = {k: before.get(k) for k in watched}
    assert {k: _snapshot(record).get(k) for k in watched} == before_values       # value-neutral on either contract
    if probe.status_code != 403:
        # Base without the SEC-02 operation-bound contract (current main): the route does not validate the
        # rendered token, so there is no refusal to assert.  The no-op probe above wrote nothing; the
        # enforcement assertions below are exercised on a base that enforces the token (PR #381 contract).
        assert probe.status_code == 200
        return
    forged = _single_save(env, record, "capex.C.epc_contract", "21000", {**t, "update_csrf": "bad"})
    missing = _single_save(env, record, "capex.C.epc_contract", "21000", {**t, "update_csrf": ""})
    assert forged.status_code == 403 and missing.status_code == 403
    assert {k: _snapshot(record).get(k) for k in watched} == before_values
    # the authentic rendered token is accepted, so the refusal above is attributable to the token only
    assert _single_save(env, record, "capex.C.epc_contract", "21000", t).status_code == 200


# ── SC-4: precision-safe allocation ─────────────────────────────────────────────────────────────────
def _legacy_allocate(amount_keur, children, places=8):
    """Verbatim copy of the pre-change algorithm (default Decimal context) used as the regression oracle."""
    rows = tuple(children)
    if not rows:
        return ()
    quant = Decimal("1").scaleb(-places)
    total = Decimal(str(float(amount_keur)))
    allocated, consumed = [], Decimal("0")
    for child in rows[:-1]:
        value = (total * child.weight).quantize(quant, rounding=ROUND_HALF_UP)
        allocated.append((child, value))
        consumed += value
    allocated.append((rows[-1], total - consumed))
    return tuple((child, float(value)) for child, value in allocated)


def _all_child_sets():
    sets = []
    for tech in ("solar", "wind", "data_center", "ev_charging"):
        for code in ("C.01", "C.02", "C.03", "C.04", "C.05", "C.06", "C.07", "C.08", "C.09", "C.10",
                     "C.12", "C.14", "C.15", "C.16"):
            try:
                sets.append((f"capex/{tech}/{code}", capex_children(tech, code)))
            except (KeyError, ValueError):
                continue
    for group in ("B.01", "B.02", "B.03", "B.04", "B.05", "B.06", "B.07", "B.08", "B.09", "B.10"):
        for tech in ("solar", "wind"):
            try:
                sets.append((f"opex/{tech}/{group}", opex_children(group, tech)))
            except (KeyError, ValueError):
                continue
    return sets


def test_child_catalogue_is_nonempty():
    assert len(_all_child_sets()) >= 20


def test_normal_range_results_bit_identical_to_legacy_algorithm():
    rng = random.Random(20261026)
    totals = [0.0, 1.0, 0.01, 123.456789, 20000.0, 1234567.891, 5e6, 9.99999999e9, 1e12, 1e15, 1e17, 9.9e18]
    totals += [rng.uniform(0, 1e8) for _ in range(150)] + [10 ** rng.uniform(-3, 18) for _ in range(150)]
    checked = 0
    for name, children in _all_child_sets():
        for total in totals:
            for sign in (1, -1):
                old = _legacy_allocate(sign * total, children)
                new = allocate_parent_amount(sign * total, children)
                assert new == old, (name, total)
                checked += 1
    assert checked > 5000


def test_previously_failing_large_finite_amounts_now_allocate_and_reconcile():
    failures_before = 0
    for name, children in _all_child_sets():
        for exp in (19, 20, 21, 24, 30, 60, 99, 200, 300, 305):
            total = float(f"1.2345678901234567e{exp}")
            try:
                _legacy_allocate(total, children)
            except decimal.InvalidOperation:
                failures_before += 1
            new = allocate_parent_amount(total, children)
            assert [c.code for c, _ in new] == [c.code for c in children]            # ordering preserved
            assert all(math.isfinite(v) for _, v in new)
            assert math.fsum(v for _, v in new) == pytest.approx(total, rel=1e-12), (name, exp)
    assert failures_before > 0          # the oracle really fails where the fix is needed


def test_rounding_contract_and_last_child_residual_preserved():
    children = capex_children("solar", "C.01")
    total = 1234567.8912345678
    out = allocate_parent_amount(total, children)
    quant = Decimal("1e-8")
    dec_total = Decimal(str(float(total)))
    expected = []
    consumed = Decimal(0)
    for child in children[:-1]:
        v = (dec_total * child.weight).quantize(quant, rounding=ROUND_HALF_UP)
        expected.append(v)
        consumed += v
    expected.append(dec_total - consumed)
    assert [v for _, v in out] == [float(v) for v in expected]
    # large amount: same algorithm evaluated in an independent wide context must give identical floats
    big = 3e20
    with decimal.localcontext() as ctx:
        ctx.prec = 80
        dbig = Decimal(str(float(big)))
        exp_big, consumed = [], Decimal(0)
        for child in children[:-1]:
            v = (dbig * child.weight).quantize(quant, rounding=ROUND_HALF_UP)
            exp_big.append(v)
            consumed += v
        exp_big.append(dbig - consumed)
    assert [v for _, v in allocate_parent_amount(big, children)] == [float(v) for v in exp_big]


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_non_finite_parent_amount_is_never_converted_to_a_value(bad):
    children = capex_children("solar", "C.01")
    with pytest.raises(NonFiniteParentAmountError) as err:
        allocate_parent_amount(bad, children)
    assert isinstance(err.value, ValueError)
    assert "finite" in str(err.value)
    assert allocate_parent_amount(bad, ()) == ()         # nothing to allocate: no value invented either way


def test_default_decimal_context_is_not_mutated_by_allocation():
    before = decimal.getcontext().prec
    allocate_parent_amount(1e30, capex_children("solar", "C.01"))
    assert decimal.getcontext().prec == before


# ── page-level reproduction of the display failure, and the residual case ───────────────────────────
@pytest.mark.parametrize("capacity", ["1e18", "1e100", "1e305"])
def test_workbook_page_renders_for_large_finite_capacity(env, capacity):
    record = env.create()
    t = _page_tokens(env, record)
    assert _single_save(env, record, "project_setup.technical.capacity_mw", capacity, t).status_code == 200
    assert float(_snapshot(record)["capacity_mw"]) == float(capacity)
    assert env.client.get("/v2/workbook", params={"project": record.project_code}).status_code == 200


def test_large_finite_capex_amount_page_renders_and_run_inputs_unchanged(env):
    record = env.create()
    t = _page_tokens(env, record)
    assert _single_save(env, record, "capex.C.epc_contract", "1e21", t).status_code == 200
    assert env.client.get("/v2/workbook", params={"project": record.project_code}).status_code == 200
    assert float(_snapshot(record)["capex_epc_contract_keur"]) == 1e21          # stored value is exactly what was saved


def test_residual_capacity_overflow_is_now_refused_atomically_by_the_finite_guard(env):
    """R-1 (closed by B2/C1): capacity >= ~1e306 used to persist non-finite derived totals.  The Save is now
    refused before anything is written; no plausible/zero stand-in value is ever produced."""
    record = env.create()
    t = _page_tokens(env, record)
    before = _snapshot(record)
    response = _single_save(env, record, "project_setup.technical.capacity_mw", "1e308", t)
    assert "Nothing was changed" in response.text and "representable numeric range" in response.text   # explicit refusal
    after = _snapshot(record)
    assert after == before
    assert env.client.get("/v2/workbook", params={"project": record.project_code}).status_code == 200
    with pytest.raises(NonFiniteParentAmountError):
        allocate_parent_amount(float("inf"), capex_children("solar", "C.01"))
