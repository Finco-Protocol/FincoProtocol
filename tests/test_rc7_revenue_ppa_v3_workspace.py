"""RC-7: multi-contract Save -> Run -> history/STALE chain on the existing Revenue editor route, with the Run-bound energy ledger."""
import copy
import json

import pytest

from tests.test_developer_economics_persistence_v1 import OWNER, Flow, env  # noqa: F401
from tests.test_rc2_integration_acceptance import _pi, _save_revenue
from tests.test_rc7_revenue_ppa_v3_economics import _row, _merchant, _payload, _operating


def _book(op, kind, *, ppa2_price=63.0):
    return _payload(kind, [_row(op, "ppa-a", "ppa", share=.30, price=55, end=6),
                           _row(op, "ppa-b", "ppa", share=.30, price=ppa2_price, start=6),
                           _row(op, "ppa-c", "ppa", share=.25, price=48, end=10),
                           _merchant(op)])


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_multi_contract_save_run_ledger_history_stale_and_duplicate_refusal(env, kind):
    from app.persistence.run_history_repository import get_run_history
    flow = Flow(env, kind); op = _operating(_pi(flow))
    good = _book(op, kind)
    assert _save_revenue(flow, good).status_code == 200
    run = flow.run()
    ledger = run["revenue_energy_ledger"]
    audit = run["revenue_multistream_audit"]
    assert ledger["status"] == "CONSERVED" and len(ledger["periods"]) == len(audit) == len(op)
    for row, evidence in zip(ledger["periods"], audit):
        physical = sum(s["quantity_mwh"] for s in evidence["streams"])
        assert row["physical_mwh"] == pytest.approx(physical, abs=1e-6)
    assert ledger["totals"]["unallocated_mwh"] == 0
    assert ledger["totals"]["contracted_mwh"] + ledger["totals"]["merchant_mwh"] == pytest.approx(ledger["totals"]["physical_mwh"], abs=1e-6)

    before = copy.deepcopy(get_run_history(OWNER, flow.record.project_id))
    # Duplicate contract identity: refused with an actionable error, nothing persisted, Last Run intact.
    dup = copy.deepcopy(good); dup["streams"][1]["id"] = "ppa-a"
    refused = _save_revenue(flow, dup)
    assert refused.status_code == 422 and refused.json()["error"]
    assert json.loads(flow.ws().draft_snapshot["rev_multistream_config_json"]) == good and not flow.ws().dirty
    # Deactivate a contract (remove ppa-c): saved-but-not-run is STALE and the older Run history is untouched.
    fewer = copy.deepcopy(good); fewer["streams"] = [s for s in fewer["streams"] if s["id"] != "ppa-c"]
    assert _save_revenue(flow, fewer).status_code == 200
    assert flow.ws().dirty and "STALE" in env.client.get("/v2/workbook", params=flow.project).text
    second = flow.run()
    assert second["total_revenue_keur"] != run["total_revenue_keur"]
    history = get_run_history(OWNER, flow.record.project_id)
    assert len(history) == len(before) + 1
    assert next(h for h in history if h.history_id == before[0].history_id).runtime_summary == before[0].runtime_summary
    assert not flow.ws().dirty and "CURRENT" in env.client.get("/v2/workbook", params=flow.project).text


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_non_finite_and_negative_contract_json_is_refused_by_the_save_route(env, kind):
    flow = Flow(env, kind); op = _operating(_pi(flow))
    good = _book(op, kind)
    assert _save_revenue(flow, good).status_code == 200
    for field, bad in (("price_eur_mwh", -5), ("volume_share", 1.5), ("price_eur_mwh", "NaN")):
        payload = copy.deepcopy(good); payload["streams"][0][field] = bad
        resp = _save_revenue(flow, payload)
        assert resp.status_code == 422, (field, bad)
    page = _save_revenue(flow, "{\"streams\": [{\"price_eur_mwh\": NaN}]}".replace("\"", "\""))
    assert page.status_code in (409, 422)
    assert json.loads(flow.ws().draft_snapshot["rev_multistream_config_json"]) == good
