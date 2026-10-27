"""FIN-V2-R1 R0 — an automatic reserve selection survives Save -> Reload -> Run through the real workspace."""
from __future__ import annotations

import json

import pytest

from app.workbook.bankability_config import FIELD_ID, SNAPSHOT_KEY
from tests.test_model_decision_workspace_v2 import env  # noqa: F401  (fixture)
from tests.test_model_financing_f2 import run, save


def _raw(mode, months=0):
    return json.dumps(dict(version=1, reserve=dict(mode=mode, months=months, requirement_keur=0, commitment_keur=0, fee_pct=0)))


def test_automatic_peak_survives_save_reload_run_and_save_never_runs(env):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.input_set import ProjectInputSet
    from app.workbook.bankability_config import apply_config
    from financial_engine.dsra.reserve_authority import ReservePolicyKind, classify_financing
    record = env.create("solar")
    before, old = run(env, record)
    old_summary, old_snapshot = dict(old.runtime_summary), old.snapshot_id

    raw = _raw("automatic_peak", 12)
    response = save(env, record, raw)
    assert response.status_code == 200 and "field-error-banner" not in response.text
    saved = get_workspace_state("decision-user", record.project_id)
    assert saved.draft_snapshot[SNAPSHOT_KEY] == raw                      # persisted explicitly
    assert saved.dirty and saved.last_runtime_snapshot_id == before.last_runtime_snapshot_id  # Save did not Run
    assert saved.last_runtime_summary == before.last_runtime_summary

    reloaded = get_workspace_state("decision-user", record.project_id)    # Reload
    pi = apply_config(ProjectInputSet.from_snapshot(reloaded.draft_snapshot).to_projectinputs(),
                      reloaded.draft_snapshot[SNAPSHOT_KEY], project_type="Solar")
    selection = classify_financing(pi.financing, pi.capex)
    assert selection.kind is ReservePolicyKind.PEAK_FORWARD and selection.coverage_months == 12

    after, new = run(env, record)                                         # Run
    assert new.snapshot_id != old_snapshot and dict(old.runtime_summary) == old_summary  # history immutable
    # Not NONE: a 12-month automatic reserve is a larger Project Use than the 6-month reference, so the
    # Senior sized against it differs; and the explicit 6-month selection reproduces the reference Run
    # bit-for-bit (a silent NONE would not).
    assert new.runtime_summary["senior_debt_keur"] > old_summary["senior_debt_keur"]
    assert save(env, record, _raw("automatic_peak", 6)).status_code == 200
    _, six = run(env, record)
    assert float(six.runtime_summary["senior_debt_keur"]).hex() == float(old_summary["senior_debt_keur"]).hex()
    assert save(env, record, _raw("none")).status_code == 200
    _, none = run(env, record)
    assert none.runtime_summary["senior_debt_keur"] < old_summary["senior_debt_keur"]


def test_gated_calendar_mode_is_refused_on_save_and_nothing_is_persisted(env):
    from app.persistence.workspace_repository import get_workspace_state
    record = env.create("solar")
    before, _ = run(env, record)
    response = save(env, record, _raw("automatic_forward_calendar", 9))
    assert "RESERVE_CALENDAR_V1_FUNDING_UNRESOLVED" in response.text or "field-error" in response.text
    ws = get_workspace_state("decision-user", record.project_id)
    assert ws.draft_snapshot.get(SNAPSHOT_KEY) in (None, "")
    assert ws.last_runtime_summary == before.last_runtime_summary
