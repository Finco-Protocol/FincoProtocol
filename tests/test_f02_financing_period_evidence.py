"""F03 selected-run evidence: Solar/Wind authentic persisted history and tamper controls."""
from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch

import pytest

from app.persistence.run_history_repository import get_run_history
from app.v2.f02_financing_period_evidence import (
    F02PeriodEvidenceUnavailable,
    build_f02_period_evidence,
)
from tests.test_financing_f1_sources_uses import _run, client, seeded  # noqa: F401


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_one_committed_run_period_axes_and_fail_closed_binding(client, seeded, kind):
    record = seeded[kind]
    assert client.get("/v2/workbook", params={"project": record.project_code}).status_code == 200
    _run(client, record)
    entry = get_run_history("f1-owner", record.project_id, limit=1)[0]
    with patch("app.services.production_financial_authority.run_clean_production",
               side_effect=AssertionError("read projection invoked financial Run")):
        view = build_f02_period_evidence(entry, state="CURRENT")
    assert view["identity"] == {
        "history_id": entry.history_id,
        "snapshot_id": entry.runtime_snapshot_id,
        "composite_hash": entry.composite_hash,
        "scenario_id": entry.last_runtime_scenario_id,
        "state": "CURRENT",
    }
    source_rows = entry.runtime_summary["financing_evidence"]["construction_funding"]["periods"]
    assert [r["period_index"] for r in view["construction"]["rows"]] == [r["period_index"] for r in source_rows]
    assert all(r["axis"] == "RUN_CONSTRUCTION_PERIOD" for r in view["construction"]["rows"])
    assert view["sources_uses"]["has_financing_evidence"]
    assert view["unavailable"]["construction_opening_outstanding"] == "UNAVAILABLE"
    fc = entry.runtime_summary["financing_evidence"]["construction_funding"].get("non_construction_fc_use")
    if fc is not None:
        assert view["construction"]["non_construction_fc_use"]["sources"].value == fc["total_sources_keur"]
        assert view["construction"]["non_construction_fc_use"]["residual"].value == fc["residual_keur"]
        assert view["construction"]["fc_senior_draw"]["value"] == fc.get("senior_draw_keur")
        without_draw = deepcopy(entry.runtime_summary)
        without_draw["financing_evidence"]["construction_funding"]["non_construction_fc_use"].pop("senior_draw_keur", None)
        assert build_f02_period_evidence(replace(entry, runtime_summary=without_draw), state="CURRENT")[
            "construction"]["fc_senior_draw"]["value"] is None
        malformed = deepcopy(entry.runtime_summary)
        malformed["financing_evidence"]["construction_funding"]["non_construction_fc_use"]["senior_draw_keur"] = True
        with pytest.raises(F02PeriodEvidenceUnavailable, match="FC_SENIOR_DRAW_MALFORMED"):
            build_f02_period_evidence(replace(entry, runtime_summary=malformed), state="CURRENT")
    assert view["repayment"]["axis"]["frequency"] in {"ANNUAL", "SEMIANNUAL", "QUARTERLY", "MONTHLY", "UNKNOWN"}
    assert all(r["axis"] == "RUN_DEBT_SERVICE_PERIOD" for r in view["repayment"]["rows"])
    assert view["internal_run_binding"] == "PROVEN_BACKEND_ENTRY"
    assert view["studio_credit_cross_view"] == "MITIGATED_NOT_PROVEN"
    no_digest = build_f02_period_evidence(replace(entry, integrity_evidence={}), state="CURRENT")
    assert no_digest["construction"]["rows"] and not no_digest["repayment"]["available"]
    assert no_digest["repayment"]["rows"] == ()
    with pytest.raises(F02PeriodEvidenceUnavailable, match="RUN_BINDING_MISMATCH"):
        build_f02_period_evidence(replace(entry, composite_hash="foreign"), state="CURRENT")
    with pytest.raises(F02PeriodEvidenceUnavailable, match="COMMITTED_RUN_IDENTITY_UNAVAILABLE"):
        build_f02_period_evidence(replace(entry, runtime_snapshot_id=""), state="CURRENT")


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_history_stale_and_tamper_keep_immutable_run_axes(client, seeded, kind):
    record = seeded[kind]
    assert client.get("/v2/workbook", params={"project": record.project_code}).status_code == 200
    _run(client, record)
    first = get_run_history("f1-owner", record.project_id, limit=1)[0]
    original = deepcopy(first.to_dict())
    current = build_f02_period_evidence(first, state="CURRENT")
    _run(client, record)
    second = get_run_history("f1-owner", record.project_id, limit=1)[0]
    assert second.history_id != first.history_id
    for state in ("STALE", "HISTORICAL"):
        old = build_f02_period_evidence(first, state=state)
        assert old["identity"]["snapshot_id"] == first.runtime_snapshot_id
        assert old["construction"] == current["construction"]
        assert old["repayment"]["rows"] == current["repayment"]["rows"]
    assert build_f02_period_evidence(second, state="CURRENT")["identity"]["snapshot_id"] == second.runtime_snapshot_id
    with pytest.raises(F02PeriodEvidenceUnavailable, match="RUN_BINDING_MISMATCH"):
        build_f02_period_evidence(replace(first, last_runtime_scenario_id="foreign"), state="CURRENT")
    with pytest.raises(F02PeriodEvidenceUnavailable, match="RUN_STATE_UNAVAILABLE"):
        build_f02_period_evidence(first, state="NOT_RUN")
    corrupt = deepcopy(first.integrity_evidence)
    corrupt["senior_debt"]["periods"][0]["interest"] += 1
    unverified = build_f02_period_evidence(replace(first, integrity_evidence=corrupt), state="CURRENT")
    assert not unverified["repayment"]["available"]
    assert "EVIDENCE_DIGEST_MISMATCH" in unverified["repayment"]["reason"]
    corrupt_summary = deepcopy(first.runtime_summary)
    corrupt_summary["financing_evidence"]["sources_uses"]["total_sources_keur"] += 1
    with pytest.raises(F02PeriodEvidenceUnavailable, match="SOURCES_SUBTOTAL_MISMATCH"):
        build_f02_period_evidence(replace(first, runtime_summary=corrupt_summary), state="CURRENT")
    assert first.to_dict() == original
