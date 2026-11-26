"""FINCO46: opening the workbook page (GET /v2/workbook) never rewrites a seeded working copy.

The C2B3 revenue backfill was meant to fill only ABSENT or EMPTY canonical keys, but it tested ``not value``: a
reference-seeded ``rev_co2_price_eur_mwh = 0.0`` / ``rev_co2_enabled = False`` counted as missing, so the first GET
replaced the seeded 0.0 CO2 price with the factory 1.5, changed the working copy's content hash and made every Save token
already issued to the React editor a false 409. A legitimately empty merchant curve also re-wrote the row on every GET.
Synthetic data only.
"""
from __future__ import annotations

import pytest

from app.persistence.workspace_repository import get_workspace_state
from app.services import new_project_calendar as npc
from app.services.revenue_backfill import backfill_generic_solar_reference_revenue_canonical_keys
from tests.test_model_react_wf2_projections_v1 import OWNER, env  # noqa: F401  (shared real-app fixture)


@pytest.mark.parametrize("calendar", ["dated", "legacy"])
def test_workbook_get_does_not_change_the_draft_or_invalidate_save_tokens(env, monkeypatch, calendar):
    if calendar == "legacy":
        monkeypatch.setenv(npc.ENV, "legacy")
    else:
        monkeypatch.delenv(npc.ENV, raising=False)
    record = env.create("solar")
    before = dict(get_workspace_state(OWNER, record.project_id).draft_snapshot)
    token = env.client.get("/v2/model-react/revenue", params={"project": record.project_code}).json()["save"]["content_hash"]
    for _ in range(2):
        assert env.client.get("/v2/workbook", params={"project": record.project_code}).status_code == 200
    assert get_workspace_state(OWNER, record.project_id).draft_snapshot == before
    after = env.client.get("/v2/model-react/revenue", params={"project": record.project_code}).json()["save"]["content_hash"]
    assert after == token


def test_backfill_fills_only_absent_or_empty_keys():
    class Rec:
        project_origin = "user"
        template_source = "generic_solar_reference"
    seeded = {"rev_ppa_base_tariff": "61", "rev_ppa_index": 0.0, "rev_ppa_term_years": "12", "rev_ppa_production_share": "80",
              "rev_ppa_indexation_start_policy": "cod", "rev_merchant_balancing_pct": 0.0,
              "rev_balancing_cost_eur_per_mwh": 0, "rev_co2_enabled": False, "rev_co2_price_eur_mwh": 0.0,
              "rev_merchant_price_curve_json": ""}
    assert backfill_generic_solar_reference_revenue_canonical_keys("p", "u", Rec(), seeded) is seeded
    old = {k: v for k, v in seeded.items() if k not in ("rev_co2_price_eur_mwh", "rev_ppa_index")}
    old["rev_ppa_base_tariff"] = "  "
    filled = backfill_generic_solar_reference_revenue_canonical_keys("p", "u", Rec(), old)
    assert filled["rev_co2_price_eur_mwh"] == "1.5" and filled["rev_ppa_index"] == "2.0"
    assert filled["rev_ppa_base_tariff"] == "50.0"                                 # blank string is EMPTY
    assert filled["rev_co2_enabled"] is False and filled["rev_merchant_balancing_pct"] == 0.0   # values kept
