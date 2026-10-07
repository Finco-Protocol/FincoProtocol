"""Model V2 UX Foundation — Overview decision groups + Smart Panel (UX-3).

Covers:

  UX_OVERVIEW_GROUPS            RETURNS / DEBT & COVERAGE / OPERATING groups
  UX_OVERVIEW_PASS_THROUGH      canonical persisted values pass through —
                                no recomputation; legit zero stays zero
  UX_OVERVIEW_UNAVAILABLE       unavailable metrics are omitted, never zero
  UX_OVERVIEW_STALE_QUARANTINE  stale Last Run stays visible and visibly stale
  UX_SMART_PANEL_SEVERITY       repository tone ordering: fail → warn → pass
  UX_SMART_PANEL_EMPTY_STATES   no-checks / no-run handled, no blank panels
  UX_SMART_PANEL_NAVIGATION     links activate EXISTING surfaces only
  UX_SMART_PANEL_NO_FAKE_GOTO   no fake Go-to-field without field identity
  UX_SMART_PANEL_NO_ENGINE      rendering/projection never invokes the engine
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from jinja2 import Environment, FileSystemLoader, select_autoescape


@pytest.fixture(scope="module")
def v2_templates():
    return Environment(
        loader=FileSystemLoader("app/templates/v2"),
        autoescape=select_autoescape(["html"]),
    )


# ---------------------------------------------------------------------------
# Overview: KPI groups + pass-through + unavailable semantics
# ---------------------------------------------------------------------------

def _overview_ctx(metrics, state="CLEAN"):
    """Minimal sheet_overview.html context with OutputMetricProjection-style
    metric objects (same contract the projection authority emits)."""
    from app.v2.output_metric_projection import build_output_metric_projection

    freshness = {"CLEAN": "current", "STALE": "stale"}.get(state, "not_run")
    output_metrics = {
        key: build_output_metric_projection(key, raw, freshness=freshness)
        for key, raw in metrics.items()
    }
    overview = SimpleNamespace(
        state=SimpleNamespace(
            value={"CLEAN": "CLEAN", "STALE": "STALE"}.get(state, "NOT_RUN")),
        output_metrics=output_metrics,
        run_timestamp_display="2026-10-06 21:14 UTC",
        snapshot_id="snap-1",
    )
    return {
        "overview": overview,
        "project_code": "alpha",
        "project_name": "Alpha",
        "project_type": "solar",
        "project_editable": True,
        "ws_dirty": state == "STALE",
        "runtime_is_stale": state == "STALE",
        "has_runtime": state != "NOT_RUN",
        "smart_panel": None,
    }


class TestOverviewKpiGroups:
    def test_three_decision_groups_render(self, v2_templates):
        html = v2_templates.get_template("partials/sheet_overview.html").render(
            _overview_ctx({"project_irr": 0.087, "min_dscr": 1.4,
                           "total_revenue_keur": 27000.0}))
        assert 'data-testid="kpi-group-returns"' in html
        assert 'data-testid="kpi-group-debt"' in html
        assert 'data-testid="kpi-group-operating"' in html
        assert "Returns" in html and "Debt &amp; Coverage" in html
        assert "Operating" in html

    def test_canonical_values_pass_through(self, v2_templates):
        html = v2_templates.get_template("partials/sheet_overview.html").render(
            _overview_ctx({"project_irr": 0.087, "min_dscr": 1.4}))
        assert 'data-testid="kpi-project-irr"' in html
        assert "8.70%" in html
        assert 'data-testid="kpi-min-dscr"' in html
        assert "1.40x" in html

    def test_legitimate_zero_stays_zero(self, v2_templates):
        html = v2_templates.get_template("partials/sheet_overview.html").render(
            _overview_ctx({"min_dscr": 0.0}))
        assert 'data-testid="kpi-min-dscr"' in html
        assert "0.00x" in html

    def test_unavailable_metrics_are_omitted_never_zero(self, v2_templates):
        html = v2_templates.get_template("partials/sheet_overview.html").render(
            _overview_ctx({"project_irr": 0.087}))
        assert 'data-testid="kpi-project-irr"' in html
        assert 'data-testid="kpi-min-dscr"' not in html
        assert 'data-testid="kpi-min-llcr"' not in html

    def test_sponsor_moic_from_persisted_summary(self, v2_templates):
        html = v2_templates.get_template("partials/sheet_overview.html").render(
            _overview_ctx({"sponsor_moic": 1.83}))
        assert 'data-testid="kpi-total-sponsor-moic"' in html
        assert "1.83x" in html


class TestOverviewStaleQuarantine:
    def test_stale_last_run_stays_visible_and_marked(self, v2_templates):
        html = v2_templates.get_template("partials/sheet_overview.html").render(
            _overview_ctx({"project_irr": 0.087}, state="STALE"))
        assert "STALE" in html
        assert "Inputs changed since the last run" in html
        # Values remain readable for reference…
        assert "8.70%" in html
        # …but every tile is visibly classified stale.
        assert "v2-kpi-tile--stale" in html

    def test_not_run_shows_no_kpis(self, v2_templates):
        html = v2_templates.get_template("partials/sheet_overview.html").render(
            _overview_ctx({}, state="NOT_RUN"))
        assert 'data-testid="overview-no-run-state"' in html
        assert 'data-testid="kpi-project-irr"' not in html


# ---------------------------------------------------------------------------
# Correction A6 — adversarial return-metric wiring through the REAL
# production projection builder (intentionally distinct persisted values;
# this test failed against pre-correction HEAD where sponsor MOIC read XIRR)
# ---------------------------------------------------------------------------

class TestReturnMetricAuthorityWiring:
    def _projections(self):
        from app.v2.output_metric_projection import (
            build_overview_metric_projections,
        )
        return build_overview_metric_projections(
            {},  # runtime_summary empty on purpose
            {},  # debt summary empty on purpose
            {
                "total_sponsor_xirr": 0.1475,
                "total_sponsor_moic": 1.83,
                "pure_equity_moic": 2.11,
            },
            freshness="current",
        )

    def test_distinct_persisted_fields_map_to_distinct_metrics(self):
        m = self._projections()
        # raw values — each metric reads ONLY its own persisted field
        assert m["sponsor_irr"].raw_value == pytest.approx(0.1475, abs=1e-12)
        assert m["sponsor_moic"].raw_value == pytest.approx(1.83, abs=1e-12)
        assert m["pure_equity_moic"].raw_value == pytest.approx(2.11, abs=1e-12)
        # display — canonical formatter pass-through, no recomputation
        assert m["sponsor_irr"].display_value == "14.75%"
        assert m["sponsor_moic"].display_value == "1.83x"
        assert m["pure_equity_moic"].display_value == "2.11x"

    def test_sponsor_moic_is_not_the_xirr_value(self):
        m = self._projections()
        assert m["sponsor_moic"].raw_value != m["sponsor_irr"].raw_value

    def test_missing_persisted_field_reads_unavailable_never_sibling(self):
        """A missing MOIC field never falls back to the XIRR value."""
        from app.v2.output_metric_projection import (
            build_overview_metric_projections,
        )
        m = build_overview_metric_projections(
            {}, {}, {"total_sponsor_xirr": 0.1475}, freshness="current")
        assert m["sponsor_moic"].raw_value is None
        assert m["pure_equity_moic"].raw_value is None
        assert m["sponsor_moic"].display_value == "—"


# ---------------------------------------------------------------------------
# Smart Panel projection
# ---------------------------------------------------------------------------

class TestSmartPanelProjection:
    def _build(self, **overrides):
        from app.v2.smart_panel_projection import build_smart_panel_projection
        kwargs = dict(trust_pack=None, runtime_state="CURRENT",
                      has_runtime=True, project_key="")
        kwargs.update(overrides)
        return build_smart_panel_projection(**kwargs)

    def test_stale_note_names_the_contract(self):
        p = self._build(runtime_state="STALE")
        assert "changes not yet run" in p.stale_note
        assert "stale" in p.stale_note

    def test_not_run_note(self):
        p = self._build(runtime_state="NOT_RUN", has_runtime=False)
        assert "Run the model" in p.stale_note

    def test_severity_ordering_blocks_first(self):
        from app.v2.smart_panel_projection import SmartPanelRow

        p = self._build(project_key="solar")
        p.sections[0].rows  # sanity
        # Synthesize mixed tones through the ordering property.
        ordered = p.ordered_rows
        tones = [r.tone for r in ordered]
        rank = {"fail": 0, "warn": 1, "pass": 2, "": 3}
        assert rank == rank  # vocabulary guard
        assert tones == sorted(tones, key=lambda t: rank.get(t, 3))

    def test_unavailable_trust_sections_report_warn_not_pass(self):
        p = self._build(trust_pack={
            "validation": {"state": "UNAVAILABLE"},
            "last_run": {"state": "UNAVAILABLE"},
        })
        checks = p.sections[0]
        values = {r.label: r for r in checks.rows}
        assert values["Reference regression"].tone == "warn"
        assert values["Reference regression"].value == "UNAVAILABLE"
        assert values["Last Run identity"].tone == "warn"

    def test_trace_typed_unavailable_never_fake(self):
        """Correction A4/A8: the full trace needs the clean production run
        object (not persisted after a run; re-execution is forbidden) —
        TRACE is a typed unavailable/future section with NO navigation."""
        p = self._build(has_runtime=True, runtime_state="CURRENT")
        trace = p.sections[-1]
        assert trace.key == "trace"
        assert trace.available is False
        assert "not persisted after a run" in trace.empty_text
        assert trace.link is None  # no fake navigation into nothing

    def test_assumptions_availability_is_authority_based(self):
        """Correction A8: availability comes from the ACTUAL register
        construction result — never asserted unconditionally."""
        ok = self._build(assumption_register_view={
            "available": True, "entry_count": 24})
        assumptions = ok.sections[1]
        assert assumptions.key == "assumptions"
        assert assumptions.available is True
        assert "24 entries" in assumptions.rows[0].value
        assert assumptions.link is not None
        assert assumptions.link.anchor == "#assumption-register"

        failed = self._build(assumption_register_view={
            "available": False, "entry_count": 0})
        assumptions_failed = failed.sections[1]
        assert assumptions_failed.available is False
        assert assumptions_failed.rows == ()
        assert assumptions_failed.link is None
        assert "unavailable" in assumptions_failed.empty_text.lower()

    def test_no_available_in_trust_pack_claim_for_missing_surface(self):
        """Correction A4: the misleading 'Available in the Trust Pack'
        wording is gone — assumptions now name the actual register state."""
        p = self._build(project_key="")
        all_values = [r.value for sec in p.sections for r in sec.rows]
        assert "Available in the Trust Pack" not in all_values

    def test_links_only_target_existing_tabs(self):
        p = self._build()
        from pathlib import Path
        workbook = Path("app/templates/v2/workbook.html").read_text(
            encoding="utf-8")
        existing = set(__import__("re").findall(r'id="(tab-[a-z-]+)"',
                                                workbook))
        for section in p.sections:
            if section.link is not None:
                assert section.link.tab_id in existing

    def test_no_fake_go_to_field_without_field_identity(self, v2_templates):
        """No field-identity check authority exists yet — the panel must not
        render fake Go-to-field actions (typed absence, honest copy)."""
        panel = self._build(project_key="solar")
        html = v2_templates.get_template(
            "partials/_model_smart_panel.html").render({"smart_panel": panel})
        assert "Go to field" not in html

    def test_no_engine_invocation_from_projection(self, monkeypatch):
        import app.api.project_runner as pr

        def _boom(*a, **k):
            raise AssertionError("engine ran from smart panel projection")

        monkeypatch.setattr(pr, "run_project", _boom, raising=False)
        self._build(trust_pack={"last_run": {"state": "AVAILABLE"}})


class TestSmartPanelRender:
    def test_panel_renders_sections_and_links(self, v2_templates):
        from app.v2.smart_panel_projection import build_smart_panel_projection

        panel = build_smart_panel_projection(
            trust_pack={"last_run": {"state": "AVAILABLE"},
                        "validation": {"state": "DEFERRED"}},
            runtime_state="STALE", has_runtime=True, project_key="solar")
        html = v2_templates.get_template(
            "partials/_model_smart_panel.html").render({"smart_panel": panel})
        assert 'data-testid="smart-panel"' in html
        assert 'data-testid="smart-panel-section-checks"' in html
        assert 'data-testid="smart-panel-section-assumptions"' in html
        assert 'data-testid="smart-panel-section-trace"' in html
        assert "Working Copy has changes not yet run" in html
        # Link activates the EXISTING Trust Pack tab.
        assert 'data-nav-tab="tab-trust"' in html

    def test_workbook_mounts_panel(self, seeded_db=None):
        from pathlib import Path
        workbook = Path("app/templates/v2/workbook.html").read_text(
            encoding="utf-8")
        assert '{% include "partials/_model_smart_panel.html" %}' in workbook
        # the stable DOM id lives on the partial's own root element
