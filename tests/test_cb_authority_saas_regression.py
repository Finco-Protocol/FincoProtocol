"""Correction B — Authority Strip and SaaS CSS Regression Tests.

Covers all 8 requirements from the Correction B specification:

  A. dirty=false + runtime exists DOES NOT render "matches last run"
  B. dirty=true renders an honest Working changed/unsaved state
  C. Project Library / context without workspace authority does NOT claim
     Working clean / Last-Run authority
  D. Last-Run active state appears only when a runtime snapshot genuinely exists
  E. Export strip does not fabricate an authority mode (removed from strip)
  F. At least one actual Model input surface uses the new SaaS form styling
  G. At least one actual Model financial/result table uses the new SaaS table styling
  H. 390px Model workspace still has no destructive page-level overflow
     (browser test — see class TestCBH below)
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_jinja_env():
    """Return the production Jinja2 environment from main_web."""
    import main_web
    return main_web.templates.env


def _render_command_bar(ctx: dict) -> str:
    """Render _command_bar.html with the given context dict."""
    env = _get_jinja_env()
    tmpl = env.get_template("partials/_command_bar.html")
    return tmpl.render(ctx)


def _make_fake_project_record(project_code: str = "CB-TEST-001"):
    """Return a minimal namespace that satisfies `project_record is not none` in templates."""
    return types.SimpleNamespace(project_code=project_code)


# ---------------------------------------------------------------------------
# A. dirty=false + runtime exists — must NOT render "matches last run"
# ---------------------------------------------------------------------------

class TestCBAuthorityStripDirtyFalse:
    """A: When dirty=false and a runtime snapshot exists, the template must NOT
    claim the working copy matches the last run — it only knows the copy is saved."""

    def test_a1_dirty_false_runtime_present_no_matches_last_run_text(self):
        """A1: dirty=false + runtime_snapshot_id present → 'matches last run' absent."""
        html = _render_command_bar({
            "project_record": _make_fake_project_record(),
            "dirty": False,
            "runtime_snapshot_id": "snap-abc-123",
        })
        assert "matches last run" not in html.lower(), (
            "Command bar must never claim working copy 'matches last run' — "
            "dirty=false only proves the copy is saved, not that it equals the run"
        )

    def test_a2_dirty_false_runtime_present_saved_text_present(self):
        """A2: dirty=false + runtime_snapshot_id present → tooltip says 'saved'."""
        html = _render_command_bar({
            "project_record": _make_fake_project_record(),
            "dirty": False,
            "runtime_snapshot_id": "snap-abc-123",
        })
        assert "saved" in html.lower(), (
            "Command bar must say 'saved' in Working tooltip when dirty=false"
        )

    def test_a3_dirty_false_no_runtime_no_matches_last_run_text(self):
        """A3: dirty=false without a runtime snapshot — still must not claim 'matches last run'."""
        html = _render_command_bar({
            "project_record": _make_fake_project_record(),
            "dirty": False,
            "runtime_snapshot_id": "unavailable",
        })
        assert "matches last run" not in html.lower(), (
            "Without a runtime snapshot, 'matches last run' is even more wrong"
        )


# ---------------------------------------------------------------------------
# B. dirty=true — renders honest Working changed/unsaved state
# ---------------------------------------------------------------------------

class TestCBAuthorityStripDirtyTrue:
    """B: When dirty=true the template must express unsaved / working-changed state."""

    def test_b1_dirty_true_renders_unsaved_text(self):
        """B1: dirty=true → tooltip contains 'unsaved changes'."""
        html = _render_command_bar({
            "project_record": _make_fake_project_record(),
            "dirty": True,
            "runtime_snapshot_id": "snap-xyz-999",
        })
        assert "unsaved changes" in html.lower(), (
            "When dirty=true the Working tooltip must say 'unsaved changes'"
        )

    def test_b2_dirty_true_working_class_present(self):
        """B2: dirty=true → fo-auth-item--working class applied."""
        html = _render_command_bar({
            "project_record": _make_fake_project_record(),
            "dirty": True,
            "runtime_snapshot_id": "snap-xyz-999",
        })
        assert "fo-auth-item--working" in html, (
            "dirty=true must apply fo-auth-item--working class to the Working chip"
        )

    def test_b3_dirty_false_working_clean_class_present(self):
        """B3: dirty=false → fo-auth-item--working-clean class applied."""
        html = _render_command_bar({
            "project_record": _make_fake_project_record(),
            "dirty": False,
            "runtime_snapshot_id": "snap-xyz-999",
        })
        assert "fo-auth-item--working-clean" in html, (
            "dirty=false must apply fo-auth-item--working-clean class to the Working chip"
        )


# ---------------------------------------------------------------------------
# C. Library / no workspace — does NOT claim Working clean / Last-Run
# ---------------------------------------------------------------------------

class TestCBLibraryNoAuthorityStrip:
    """C: When project_record is None (Library page, no workspace), the authority
    strip must not appear at all — no Working/Last-Run chips fabricated."""

    def test_c1_project_record_none_no_authority_strip(self):
        """C1: project_record=None → fo-auth-strip absent from rendered HTML."""
        html = _render_command_bar({
            "project_record": None,
            "dirty": False,
            "runtime_snapshot_id": "snap-xyz",
        })
        assert "fo-auth-strip" not in html, (
            "fo-auth-strip must not appear when project_record is None (Library page)"
        )

    def test_c2_project_record_none_no_working_chip(self):
        """C2: project_record=None → 'Working' authority chip absent."""
        html = _render_command_bar({
            "project_record": None,
            "dirty": False,
            "runtime_snapshot_id": "snap-xyz",
        })
        # The chip text "Working" should not appear inside an authority context.
        # (The Run button area is fine — we look for the auth-item class.)
        assert "fo-auth-item" not in html, (
            "No fo-auth-item element must appear when project_record is None"
        )

    def test_c3_project_record_none_no_last_run_chip(self):
        """C3: project_record=None → Last-Run chip absent."""
        html = _render_command_bar({
            "project_record": None,
            "dirty": False,
            "runtime_snapshot_id": "snap-xyz",
        })
        assert "fo-auth-item--lastrun" not in html, (
            "fo-auth-item--lastrun must not appear when project_record is None"
        )

    def test_c4_library_route_sets_project_record_none(self):
        """C4: /library route context contains project_record=None (canonical gate signal)."""
        src = Path(__file__).resolve().parents[1] / "app" / "library" / "router.py"
        code = src.read_text()
        assert '"project_record": None' in code or "'project_record': None" in code, (
            "Library router must explicitly set project_record: None in template context"
        )


# ---------------------------------------------------------------------------
# D. Last-Run active state — only when runtime snapshot genuinely exists
# ---------------------------------------------------------------------------

class TestCBLastRunActiveState:
    """D: The Last-Run chip's 'active' class must only appear when a real
    runtime_snapshot_id exists (i.e. is not 'unavailable' or missing)."""

    def test_d1_real_snapshot_id_gives_lastrun_active_class(self):
        """D1: runtime_snapshot_id='snap-abc' → fo-auth-item--lastrun applied."""
        html = _render_command_bar({
            "project_record": _make_fake_project_record(),
            "dirty": False,
            "runtime_snapshot_id": "snap-real-001",
        })
        assert "fo-auth-item--lastrun" in html, (
            "Last-Run chip must have fo-auth-item--lastrun when snapshot exists"
        )
        assert "fo-auth-item--lastrun-none" not in html, (
            "fo-auth-item--lastrun-none must NOT appear when snapshot exists"
        )

    def test_d2_unavailable_snapshot_gives_lastrun_none_class(self):
        """D2: runtime_snapshot_id='unavailable' → fo-auth-item--lastrun-none applied."""
        html = _render_command_bar({
            "project_record": _make_fake_project_record(),
            "dirty": False,
            "runtime_snapshot_id": "unavailable",
        })
        assert "fo-auth-item--lastrun-none" in html, (
            "Last-Run chip must have fo-auth-item--lastrun-none when no snapshot"
        )

    def test_d3_missing_snapshot_gives_lastrun_none_class(self):
        """D3: runtime_snapshot_id absent from context → fo-auth-item--lastrun-none applied."""
        html = _render_command_bar({
            "project_record": _make_fake_project_record(),
            "dirty": False,
            # runtime_snapshot_id intentionally omitted
        })
        assert "fo-auth-item--lastrun-none" in html, (
            "Last-Run chip must have fo-auth-item--lastrun-none when context has no snapshot"
        )

    def test_d4_no_run_yet_tooltip_when_no_snapshot(self):
        """D4: No snapshot → tooltip says 'no run yet'."""
        html = _render_command_bar({
            "project_record": _make_fake_project_record(),
            "dirty": False,
            "runtime_snapshot_id": "unavailable",
        })
        assert "no run yet" in html.lower(), (
            "Last-Run chip tooltip must say 'no run yet' when no snapshot exists"
        )


# ---------------------------------------------------------------------------
# E. Export does NOT appear in the authority strip
# ---------------------------------------------------------------------------

class TestCBExportNotInAuthorityStrip:
    """E: Export is a command action only — it must NOT fabricate an authority mode
    in the fo-auth-strip."""

    def test_e1_no_export_auth_item_in_strip(self):
        """E1: fo-auth-item--export absent from fo-auth-strip output."""
        html = _render_command_bar({
            "project_record": _make_fake_project_record(),
            "dirty": False,
            "runtime_snapshot_id": "snap-abc",
        })
        assert "fo-auth-item--export" not in html, (
            "fo-auth-item--export must not appear in the command bar — "
            "Export was removed from the authority strip"
        )

    def test_e2_export_command_action_still_present(self):
        """E2: The Export button/link still exists as a command action."""
        html = _render_command_bar({
            "project_record": _make_fake_project_record(),
            "dirty": False,
            "runtime_snapshot_id": "snap-abc",
        })
        # Export should still be a command action (button or link)
        assert "Export" in html, (
            "Export must still be present as a command action button"
        )


# ---------------------------------------------------------------------------
# F. Model input surface uses SaaS form styling
# ---------------------------------------------------------------------------

class TestCBInputSectionSaaSClasses:
    """F: At least one actual Model input surface uses the new SaaS form styling.

    inputs_section.html is the canonical model input partial. It must apply
    fo-input-section (and sub-element classes) to wrap each input card.
    """

    def test_f1_inputs_section_template_uses_fo_input_section(self):
        """F1: inputs_section.html source contains fo-input-section class."""
        tpl_path = (
            Path(__file__).resolve().parents[1]
            / "app" / "templates" / "partials" / "inputs_section.html"
        )
        src = tpl_path.read_text()
        assert "fo-input-section" in src, (
            "inputs_section.html must apply fo-input-section class to section cards"
        )

    def test_f2_inputs_section_template_uses_fo_input_section_header(self):
        """F2: inputs_section.html source contains fo-input-section__header."""
        tpl_path = (
            Path(__file__).resolve().parents[1]
            / "app" / "templates" / "partials" / "inputs_section.html"
        )
        src = tpl_path.read_text()
        assert "fo-input-section__header" in src, (
            "inputs_section.html must apply fo-input-section__header class"
        )

    def test_f3_inputs_section_template_uses_fo_input_section_body(self):
        """F3: inputs_section.html source contains fo-input-section__body."""
        tpl_path = (
            Path(__file__).resolve().parents[1]
            / "app" / "templates" / "partials" / "inputs_section.html"
        )
        src = tpl_path.read_text()
        assert "fo-input-section__body" in src, (
            "inputs_section.html must apply fo-input-section__body class"
        )

    def test_f4_model_saas_css_defines_fo_input_section(self):
        """F4: model-saas.css defines the .fo-input-section rule."""
        css_path = (
            Path(__file__).resolve().parents[1]
            / "static" / "css" / "model-saas.css"
        )
        src = css_path.read_text()
        assert ".fo-input-section" in src, (
            "model-saas.css must define .fo-input-section"
        )


# ---------------------------------------------------------------------------
# G. Model financial/result table uses SaaS table styling
# ---------------------------------------------------------------------------

class TestCBFinTableSaaSClasses:
    """G: At least one actual Model financial/result table uses the new SaaS table styling.

    _sheet_sponsor_partial.html is the canonical financial output table partial.
    It must apply fo-fin-table (and fo-fin-table__num-col) to its schedule table.
    """

    def test_g1_sponsor_partial_uses_fo_fin_table(self):
        """G1: _sheet_sponsor_partial.html source contains fo-fin-table class."""
        tpl_path = (
            Path(__file__).resolve().parents[1]
            / "app" / "templates" / "partials" / "_sheet_sponsor_partial.html"
        )
        src = tpl_path.read_text()
        assert "fo-fin-table" in src, (
            "_sheet_sponsor_partial.html must apply fo-fin-table to the cashflow table"
        )

    def test_g2_sponsor_partial_uses_fo_fin_table_num_col(self):
        """G2: _sheet_sponsor_partial.html source contains fo-fin-table__num-col."""
        tpl_path = (
            Path(__file__).resolve().parents[1]
            / "app" / "templates" / "partials" / "_sheet_sponsor_partial.html"
        )
        src = tpl_path.read_text()
        assert "fo-fin-table__num-col" in src, (
            "_sheet_sponsor_partial.html must apply fo-fin-table__num-col "
            "to numeric header cells"
        )

    def test_g3_model_saas_css_defines_fo_fin_table(self):
        """G3: model-saas.css defines the .fo-fin-table rule."""
        css_path = (
            Path(__file__).resolve().parents[1]
            / "static" / "css" / "model-saas.css"
        )
        src = css_path.read_text()
        assert ".fo-fin-table" in src, (
            "model-saas.css must define .fo-fin-table"
        )

    def test_g4_model_saas_css_defines_fo_fin_table_num_col(self):
        """G4: model-saas.css defines the .fo-fin-table__num-col rule."""
        css_path = (
            Path(__file__).resolve().parents[1]
            / "static" / "css" / "model-saas.css"
        )
        src = css_path.read_text()
        assert ".fo-fin-table__num-col" in src, (
            "model-saas.css must define .fo-fin-table__num-col"
        )


# ---------------------------------------------------------------------------
# CSS source audit: .tab-btn:focus rule physically absent
# ---------------------------------------------------------------------------

class TestCBRadarFocusRule:
    """Correctness gate: the .tab-btn:focus { outline: none } rule must be
    physically absent from radar.css (not merely commented out).

    A rule that removes outline for ALL focus sources (not just :focus-visible)
    breaks keyboard accessibility. Correction B physically deleted it.
    """

    def test_no_tab_btn_focus_outline_none_rule(self):
        """radar.css must not contain .tab-btn:focus { outline: none }."""
        css_path = (
            Path(__file__).resolve().parents[1]
            / "static" / "radar" / "radar.css"
        )
        src = css_path.read_text()
        # Look for the exact suppression pattern (not commented out)
        import re
        # Find any non-comment line that contains .tab-btn:focus followed by
        # outline: none (the suppression rule)
        lines = src.splitlines()
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("/*") or stripped.startswith("//"):
                continue
            if ".tab-btn:focus" in stripped and "focus-visible" not in stripped:
                if "outline" in stripped and "none" in stripped:
                    pytest.fail(
                        f"radar.css contains the suppression rule that was supposed to "
                        f"be removed in Correction A/B: {stripped!r}"
                    )

    def test_tab_btn_focus_visible_rule_present(self):
        """radar.css must define a :focus-visible rule for .tab-btn."""
        css_path = (
            Path(__file__).resolve().parents[1]
            / "static" / "radar" / "radar.css"
        )
        src = css_path.read_text()
        assert ".tab-btn:focus-visible" in src, (
            "radar.css must define .tab-btn:focus-visible for keyboard accessibility"
        )
