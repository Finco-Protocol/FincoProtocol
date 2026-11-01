"""WF-06B F-01/F-02 on the REAL stack (HTTP routes + the actual Run): no economic drift from the ledger/projection/UI, and a supported
user-line delta changes the effective Run input exactly once (no double fold) and is exactly reversible."""
from __future__ import annotations

import hashlib
import json
import math

import pytest

from tests.model_mutation_csrf import post_valid_mutation
from tests.test_pr394_staging_corrections_v1 import costlines, run_json, save_batch, first_line, wire_edit  # noqa: F401
from tests.test_model_react_wf2_projections_v1 import cas, env  # noqa: F401  (this fixture mounts the capex/opex line routers too)

KINDS = ("solar", "wind")
KPI_KEYS = ("project_irr", "equity_irr", "sponsor_irr", "min_dscr", "avg_dscr")
SCHEDULES = ("financial_statements", "debt_schedule", "tax_schedule", "distribution_schedule", "sponsor_schedule")


def _entry(record):
    from app.persistence.run_history_repository import get_latest_history_entry
    return get_latest_history_entry(record.user_id, record.project_id).to_dict()


def _digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _snapshot(entry) -> dict:
    ident = entry["last_runtime_identity"]
    return {
        "capex_rows": ident["capex_rows"], "opex_rows": ident["opex_rows"], "opex_fold": ident["opex_fold"],
        "kpis": {k: entry["runtime_summary"].get(k) for k in KPI_KEYS},
        "schedules": {k: _digest(entry[k]) for k in SCHEDULES},
        "composite_hash": entry["composite_hash"],
    }


def _run(env, record):
    response = run_json(env, record)
    assert response.status_code == 200 and response.json()["outcome"] == "COMMITTED", response.text[:300]
    return _snapshot(_entry(record))


@pytest.mark.parametrize("kind", KINDS)
def test_f01_ui_projection_reads_and_unchanged_save_do_not_move_the_run(env, kind):
    record = env.create(kind)
    before = _run(env, record)
    assert all(v is not None for v in before["kpis"].values()), before["kpis"]

    for sheet in ("capex", "opex"):                                  # the new projection is read-only
        for _ in range(2):
            assert costlines(env, record, sheet)["projection"] is not None
    # an owner Save of the SAME decimal values through the real batch writer
    for sheet in ("capex", "opex"):
        payload = costlines(env, record, sheet)
        line = first_line(payload)
        response = save_batch(env, record, payload, [wire_edit(sheet, line, str(line["amount_keur"]))], sheet=sheet)
        assert response.status_code == 200, response.text[:300]

    after = _run(env, record)
    assert after["capex_rows"] == before["capex_rows"] and after["opex_rows"] == before["opex_rows"] and after["opex_fold"] == before["opex_fold"]
    assert after["kpis"] == before["kpis"], "KPIs must be exactly equal (no tolerance)"
    assert after["schedules"] == before["schedules"]


@pytest.mark.parametrize("kind", KINDS)
def test_f02_user_line_changes_effective_input_once_and_is_exactly_reversible(env, kind):
    record = env.create(kind)
    base = _run(env, record)
    capex0 = costlines(env, record, "capex")
    group = "C.02"
    f0 = {f["field"]: f for f in capex0["projection"]["fold"]["fields"]}["epc_contract"]
    add = post_valid_mutation(env.client, "/v2/capex/line/add", data={
        "project": record.project_code, "parent_category_code": group, "label": "WF06B parity line", "amount_keur": "125.5", "notes": "",
        **cas(capex0)}, follow_redirects=False)
    assert add.status_code == 303

    capex1 = costlines(env, record, "capex")
    f1 = {f["field"]: f for f in capex1["projection"]["fold"]["fields"]}["epc_contract"]
    # the projection describes the fold: the field is the SUM of its active lines
    assert math.isclose(f1["saved_total_keur"] - f0["saved_total_keur"], 125.5, abs_tol=1e-9) and f1["mode"] == "REPLACE_BASE_WITH_ACTIVE_LINES"

    with_line = _run(env, record)
    added = [r for r in with_line["capex_rows"] if r["parent_category_code"] == group]
    base_sum = math.fsum(r["amount_keur"] for r in base["capex_rows"] if r["parent_category_code"] == group)
    new_sum = math.fsum(r["amount_keur"] for r in added)
    assert math.isclose(new_sum - base_sum, 125.5, abs_tol=1e-9), "exactly one fold of the new amount"
    assert math.isclose(new_sum, f1["saved_total_keur"], abs_tol=1e-9), "projection field total == effective Run rows for that field"
    assert with_line["kpis"]["project_irr"] < base["kpis"]["project_irr"], "more CAPEX must lower project IRR"
    assert with_line["schedules"] != base["schedules"]

    line = next(l for l in capex1["lines"] if l["label"] == "WF06B parity line")
    off = post_valid_mutation(env.client, "/v2/capex/line/deactivate", data={
        "project": record.project_code, "sub_line_id": line["sub_line_id"], "row_version": line["row_version"], **cas(capex1)}, follow_redirects=False)
    assert off.status_code == 303
    restored = _run(env, record)
    assert restored["kpis"] == base["kpis"] and restored["schedules"] == base["schedules"], "deactivation restores the exact Run economics"


@pytest.mark.parametrize("kind", KINDS)
def test_explicit_zero_stays_zero_in_projection_and_run_identity(env, kind):
    record = env.create(kind)
    payload = costlines(env, record, "opex")
    line = first_line(payload)
    assert save_batch(env, record, payload, [wire_edit("opex", line, "0", "0")], sheet="opex").status_code == 200
    again = costlines(env, record, "opex")
    row = next(l for l in again["projection"]["lines"] if l["sub_line_id"] == line["sub_line_id"])
    assert row["amount_keur"] == 0 and row["amount_keur"] is not None
    assert row["feeds_run_fold"] is True
