"""GF-F05 — Scenario-card canonical freshness focused regressions.

T1  modern CURRENT: post-Run composite hash matches → effective scenario = CURRENT
T2  modern STALE:   Working edit → hash mismatch   → effective scenario = STALE
T3  reopen gap:     stale persists through GET (GET path uses canonical hash)
T4  Run B:          after Run B effective scenario = CURRENT (not STALE)
T5  unrelated preservation: global stale does NOT downgrade other scenarios

All T1–T5 are unit-level tests against the presentation layer; no browser required.
T3 and T4 are validated via the full GF-C browser flow in
test_model_golden_flows_browser.py.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Optional
from unittest.mock import patch

import pytest

from app.v2.scenario_presentation import (
    build_scenario_presentation,
    build_scenario_presentations,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _sc(
    scenario_id: str = "sc1",
    scenario_name: str = "Base Case",
    is_base_case: bool = True,
    overrides: Optional[dict] = None,
    kpis: Optional[dict] = None,
    snapshot_hash_stored: Optional[str] = None,
    snapshot_hash_current: Optional[str] = None,
    updated_at=None,
    ran_at: Optional[str] = None,
):
    """Build a minimal fake ScenarioRecord."""
    last_run_summary = None
    if kpis is not None:
        last_run_summary = {
            "kpis": kpis,
            "scenario_snapshot_hash": snapshot_hash_stored,
            "scenario_overrides_at_run": overrides or {},
            "ran_at": ran_at or "2026-01-01T00:00:00",
        }

    # If we want to force a specific current hash, we give the sc a fake
    # snapshot attribute that the helper will serialise.
    snap = None
    if snapshot_hash_current is not None:
        # We cannot inject a pre-computed hash via the public API, so we patch
        # _scenario_snapshot_hash to return the desired value in tests that
        # need precise control.  Tests that use this param must patch the
        # helper themselves.
        pass

    return SimpleNamespace(
        scenario_id=scenario_id,
        scenario_name=scenario_name,
        is_base_case=is_base_case,
        overrides=overrides or {},
        last_run_summary=last_run_summary,
        snapshot=snap,
        base_input_set=None,
        updated_at=updated_at,
    )


# ── T1 — modern CURRENT ───────────────────────────────────────────────────────

class TestT1ModernCurrent:
    """global_is_stale=False + has_run → state must be CURRENT."""

    def test_effective_base_case_current_when_global_not_stale(self):
        """After Run B with matching composite hash: Base Case = CURRENT."""
        sc = _sc(
            kpis={"project_irr": 0.07},
            snapshot_hash_stored="abc123",
        )
        # Patch _scenario_snapshot_hash to return the SAME hash as stored.
        with patch(
            "app.v2.scenario_presentation._scenario_snapshot_hash",
            return_value="abc123",
        ):
            pres = build_scenario_presentation(sc, None, global_is_stale=False)

        assert pres.state == "CURRENT", (
            "T1: effective scenario must be CURRENT when global is not stale "
            "and scenario hash matches"
        )
        assert not pres.is_stale

    def test_list_global_not_stale_gives_current(self):
        """build_scenario_presentations with global_is_stale=False → CURRENT."""
        sc = _sc(kpis={"project_irr": 0.07}, snapshot_hash_stored=None)
        with patch(
            "app.v2.scenario_presentation._scenario_snapshot_hash",
            return_value=None,
        ):
            results = build_scenario_presentations([sc], None, global_is_stale=False)

        assert results[0].state == "CURRENT", (
            "T1: list with global_is_stale=False must not downgrade CURRENT"
        )


# ── T2 — modern STALE ─────────────────────────────────────────────────────────

class TestT2ModernStale:
    """global_is_stale=True + has_run + is_effective → state must be STALE."""

    def test_effective_base_case_stale_when_global_stale(self):
        """After Working edit: Base Case (effective) must show STALE."""
        sc = _sc(kpis={"project_irr": 0.07}, snapshot_hash_stored=None)
        with patch(
            "app.v2.scenario_presentation._scenario_snapshot_hash",
            return_value=None,
        ):
            pres = build_scenario_presentation(sc, None, global_is_stale=True)

        assert pres.state == "STALE", (
            "T2: effective Base Case must be STALE when global_is_stale=True"
        )
        assert pres.is_stale

    def test_effective_active_scenario_stale_when_global_stale(self):
        """Active non-base scenario must show STALE when global stale."""
        sc = _sc(
            scenario_id="sc-active",
            is_base_case=False,
            kpis={"project_irr": 0.08},
            snapshot_hash_stored=None,
        )
        with patch(
            "app.v2.scenario_presentation._scenario_snapshot_hash",
            return_value=None,
        ):
            pres = build_scenario_presentation(
                sc, "sc-active", global_is_stale=True
            )

        assert pres.state == "STALE", (
            "T2: active non-base effective scenario must be STALE "
            "when global_is_stale=True"
        )


# ── T5 — unrelated scenario preservation ─────────────────────────────────────

class TestT5UnrelatedPreservation:
    """global_is_stale must NOT downgrade scenarios that are not the effective one."""

    def test_non_effective_scenario_keeps_own_current_state(self):
        """A CURRENT non-effective scenario stays CURRENT despite global stale."""
        base = _sc(
            scenario_id="bc",
            is_base_case=True,
            kpis={"project_irr": 0.07},
            snapshot_hash_stored=None,
        )
        other = _sc(
            scenario_id="sc-other",
            scenario_name="Upside",
            is_base_case=False,
            kpis={"project_irr": 0.09},
            snapshot_hash_stored=None,
        )
        # Active = "bc" (Base Case explicitly active).  Other = "sc-other" is
        # the non-effective scenario.  global_is_stale=True should only
        # downgrade "bc".
        with patch(
            "app.v2.scenario_presentation._scenario_snapshot_hash",
            return_value=None,
        ):
            results = build_scenario_presentations(
                [base, other], "bc", global_is_stale=True
            )

        bc_pres = next(r for r in results if r.scenario_id == "bc")
        other_pres = next(r for r in results if r.scenario_id == "sc-other")

        assert bc_pres.state == "STALE", (
            "T5: effective (active) scenario must be STALE when global stale"
        )
        assert other_pres.state == "CURRENT", (
            "T5: non-effective scenario must remain CURRENT — "
            "its own hash is unchanged"
        )

    def test_non_effective_base_case_not_downgraded_when_active_set(self):
        """Base Case is NOT downgraded when a different scenario is active."""
        base = _sc(
            scenario_id="bc",
            is_base_case=True,
            kpis={"project_irr": 0.07},
            snapshot_hash_stored=None,
        )
        active_sc = _sc(
            scenario_id="sc-active",
            scenario_name="Active",
            is_base_case=False,
            kpis={"project_irr": 0.09},
            snapshot_hash_stored=None,
        )
        # active_scenario_id = "sc-active"; global_is_stale should only hit
        # "sc-active", not base case.
        with patch(
            "app.v2.scenario_presentation._scenario_snapshot_hash",
            return_value=None,
        ):
            results = build_scenario_presentations(
                [base, active_sc], "sc-active", global_is_stale=True
            )

        bc_pres = next(r for r in results if r.scenario_id == "bc")
        active_pres = next(r for r in results if r.scenario_id == "sc-active")

        assert active_pres.state == "STALE", (
            "T5: active scenario must be STALE when global stale"
        )
        assert bc_pres.state == "CURRENT", (
            "T5: Base Case must remain CURRENT when it is not the active scenario "
            "and its own hash is unchanged"
        )

    def test_not_run_scenario_never_downgraded(self):
        """A NOT_RUN scenario must stay NOT_RUN regardless of global_is_stale."""
        sc = _sc(scenario_id="sc-notrun", is_base_case=False, kpis=None)
        pres = build_scenario_presentation(sc, "sc-notrun", global_is_stale=True)
        assert pres.state == "NOT_RUN", (
            "T5: NOT_RUN scenario must not be downgraded to STALE"
        )

    def test_three_scenarios_only_effective_downgraded(self):
        """With three scenarios and active set, only the active one is downgraded."""
        base = _sc(
            scenario_id="bc", is_base_case=True,
            kpis={"irr": 0.07}, snapshot_hash_stored=None)
        active_sc = _sc(
            scenario_id="sc-a", scenario_name="Active", is_base_case=False,
            kpis={"irr": 0.08}, snapshot_hash_stored=None)
        third = _sc(
            scenario_id="sc-b", scenario_name="Upside", is_base_case=False,
            kpis={"irr": 0.10}, snapshot_hash_stored=None)

        with patch(
            "app.v2.scenario_presentation._scenario_snapshot_hash",
            return_value=None,
        ):
            results = build_scenario_presentations(
                [base, active_sc, third], "sc-a", global_is_stale=True
            )

        states = {r.scenario_id: r.state for r in results}
        assert states["sc-a"] == "STALE", "Active scenario must be STALE"
        assert states["bc"] == "CURRENT", "Base Case must stay CURRENT"
        assert states["sc-b"] == "CURRENT", "Unrelated scenario must stay CURRENT"


# ── GET path integration: assemble_consistent_for_get is called ───────────────

class TestGetPathIntegration:
    """Verify _scenario_list_html calls assemble_consistent_for_get for real hash."""

    def test_scenario_list_html_calls_assemble_for_real_hash(self):
        """_scenario_list_html must call assemble_consistent_for_get (not None)."""
        from unittest.mock import MagicMock, patch as _patch
        from app.v2.router import _scenario_list_html
        from app.workbook import runtime_authority as _ra

        fake_identity = SimpleNamespace(composite_hash="real-hash-abc123")
        fake_freshness = SimpleNamespace(is_stale=False)
        fake_ws = SimpleNamespace(
            active_scenario_id=None,
            dirty=False,
            last_runtime_snapshot_id="snap1",
            last_runtime_composite_hash="real-hash-abc123",
        )

        captured_hash = {}

        def capturing_resolve(ws_, current_composite_hash=None):
            captured_hash["value"] = current_composite_hash
            return fake_freshness

        with (
            _patch("app.workbook.workbook_identity.assemble_consistent_for_get",
                   return_value=fake_identity) as mock_assemble,
            _patch.object(_ra, "resolve_runtime_freshness", capturing_resolve),
            _patch("app.persistence.scenarios_repository.list_scenarios",
                   return_value=[]),
            _patch("app.v2.router._templates") as mock_tpl,
        ):
            mock_tpl.get_template.return_value.render.return_value = (
                '<div id="v2-sheet-scenarios"></div>'
            )
            _scenario_list_html("u1", "proj1", "proj1", fake_ws)

        mock_assemble.assert_called_once()
        assert captured_hash.get("value") == "real-hash-abc123", (
            "_scenario_list_html must pass the real composite hash "
            "to resolve_runtime_freshness — not None. "
            f"Got: {captured_hash.get('value')!r}"
        )
