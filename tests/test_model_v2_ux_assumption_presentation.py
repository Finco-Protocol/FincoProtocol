"""UX Correction B — Assumption Register presentation hygiene.

Presentation-only contracts over the Workflow 04 register:

  UX_ASSUMPTION_DISPLAY_FORMAT   no raw float reprs reach the UI
  UX_ASSUMPTION_CANONICAL_UNTOUCHED
                                 stored values / fingerprint byte-identical
  UX_ASSUMPTION_EV_TERMINOLOGY   EV workbooks render charging terminology;
                                 compatibility-only PPA/generation rows are
                                 omitted; canonical paths unchanged
  UX_ASSUMPTION_NON_EV_UNCHANGED Solar/Wind terminology unchanged
  UX_ASSUMPTION_ZERO_TRUTH       legitimate zero displays as zero

The register authority (app/model_v2/assumption_register.py) is NOT modified
by this correction — display problem, not an authority problem.
"""
from __future__ import annotations

import math

import pytest


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    from app.persistence import db

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "ux-assump.db"))
    db.init_db()
    yield


def _reference_pis(template_source: str):
    from app.persistence.projects_repository import (
        get_reference_by_template_source,
    )
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.project_library_service import ensure_reference_models
    from app.workbook.service import WorkbookService

    ensure_reference_models()
    ref = get_reference_by_template_source(template_source)
    assert ref is not None
    ws = get_workspace_state(ref.user_id, ref.project_id)
    return WorkbookService.build_draft_input_set_from_workspace(ws)


# ---------------------------------------------------------------------------
# B1 — presentation formatter
# ---------------------------------------------------------------------------

class TestAssumptionDisplayFormatter:
    @pytest.mark.parametrize("raw,expected", [
        (None, "—"),
        (True, "Yes"),
        (False, "No"),
        ("Central", "Central"),
        (0, "0"),                     # legitimate zero (int) → zero
        (0.0, "0"),                   # legitimate zero (float) → zero
        (250.0, "250"),
        (20.0, "20"),
        (0.02, "0.02"),
        (0.003, "0.003"),
        (1041.7021276595747, "1,041.7021"),
        (416.15999999999997, "416.16"),
        (765.9574468085107, "765.9574"),
    ])
    def test_scalar_formats(self, raw, expected):
        from app.v2.router import _format_assumption_display
        assert _format_assumption_display(raw) == expected

    def test_long_float_never_verbatim(self):
        from app.v2.router import _format_assumption_display
        display = _format_assumption_display(1041.7021276595747)
        assert "1041.7021276595747" not in display

    def test_non_finite_is_em_dash(self):
        from app.v2.router import _format_assumption_display
        assert _format_assumption_display(float("nan")) == "—"
        assert _format_assumption_display(float("inf")) == "—"

    def test_lists_and_dicts_format_numeric_leaves(self):
        from app.v2.router import _format_assumption_display
        listed = _format_assumption_display(
            [240.0, 416.15999999999997, 0.02])
        assert "416.15999999999997" not in listed
        assert "416.16" in listed
        mapped = _format_assumption_display({"y1": 1041.7021276595747})
        assert "1041.7021276595747" not in mapped
        assert "1,041.7021" in mapped


# ---------------------------------------------------------------------------
# B1/B — canonical register untouched behind the presentation layer
# ---------------------------------------------------------------------------

class TestCanonicalRegisterUntouched:
    def test_canonical_value_exact_behind_display(self, seeded_db):
        """The persisted numeric value remains exactly
        1041.7021276595747 behind the presentation layer."""
        from app.model_v2.assumption_register import (
            AssumptionSourceKind,
            RegisterContext,
            build_assumption_register,
        )
        pis = _reference_pis("generic_ev_charging_reference")
        register = build_assumption_register(
            pis.to_projectinputs(),
            RegisterContext.for_working_copy(
                state_provenance=AssumptionSourceKind.USER_INPUT,
                workbook_composite_hash=getattr(pis, "content_hash", None),
            ),
        )
        entry = next(e for e in register.entries
                     if e.canonical_path == "opex[7].y1_amount_keur")
        # exact canonical float persisted behind the presentation layer
        assert entry.value == 765.9574468085107

        steps = next(e for e in register.entries
                     if e.canonical_path == "opex[7].step_changes")
        assert [2, 1041.7021276595747] in steps.value  # nested list float

        from app.v2.router import _build_assumption_register_view
        view = _build_assumption_register_view(pis)
        row = next(r for r in view["rows"]
                   if r["path"] == "opex[7].y1_amount_keur")
        # the raw repr never reaches the display; the formatted value does
        assert "765.9574468085107" not in row["value"]
        assert "765.9574" in row["value"]
        steps_row = next(r for r in view["rows"]
                         if r["path"] == "opex[7].step_changes")
        # nested list floats formatted recursively — no raw reprs
        assert "1041.7021276595747" not in steps_row["value"]
        assert "1,041.7021" in steps_row["value"]
        assert "1,328.1702" in steps_row["value"]

    def test_fingerprint_stable_across_view_builds(self, seeded_db):
        """The view is presentation-only: the register fingerprint is
        identical no matter how often the view is built."""
        from app.model_v2.assumption_register import (
            AssumptionSourceKind,
            RegisterContext,
            build_assumption_register,
        )
        from app.v2.router import _build_assumption_register_view

        pis = _reference_pis("generic_solar_reference")

        def _fp():
            return build_assumption_register(
                pis.to_projectinputs(),
                RegisterContext.for_working_copy(
                    state_provenance=AssumptionSourceKind.USER_INPUT,
                    workbook_composite_hash=getattr(
                        pis, "content_hash", None),
                ),
            ).fingerprint

        fp1 = _fp()
        _build_assumption_register_view(pis)
        assert _fp() == fp1
        view = _build_assumption_register_view(pis)
        assert view["fingerprint"] == fp1


# ---------------------------------------------------------------------------
# B2 — EV terminology + row omission (canonical paths unchanged)
# ---------------------------------------------------------------------------

class TestEvRegisterPresentation:
    def test_ev_register_renders_charging_terminology(self, seeded_db):
        """A: EV rendered HTML contains the charging terminology…"""
        from fastapi.testclient import TestClient
        import main_web
        from app.auth import COOKIE_NAME, create_session_token

        pis = _reference_pis("generic_ev_charging_reference")
        cookies = {COOKIE_NAME: create_session_token(
            user_id="ux-assump-user", username="admin")}
        client = TestClient(main_web.app, raise_server_exceptions=True)
        _resp = client.get(
            "/v2/workbook?project=generic_ev_charging_reference-reference",
            cookies=cookies)
        assert _resp.status_code == 200 and not _resp.history
        html = _resp.text
        trust_html = html.split('id="assumption-register"')[1].split(
            "</table>")[0] if 'id="assumption-register"' in html else ""
        assert 'id="assumption-register"' in html
        for term in ("Charging Price", "Equivalent Full-Load Hours",
                     "Charging Price Escalation",
                     "Charging Price Schedule Horizon"):
            assert term in trust_html, term

    def test_ev_register_omits_ppa_and_generation_terminology(self, seeded_db):
        """A (cont.): …and does NOT contain PPA terminology; compatibility-
        only rows are omitted, not relabelled into PPA wording."""
        from fastapi.testclient import TestClient
        import main_web
        from app.auth import COOKIE_NAME, create_session_token

        cookies = {COOKIE_NAME: create_session_token(
            user_id="ux-assump-user2", username="admin")}
        client = TestClient(main_web.app, raise_server_exceptions=True)
        _reference_pis("generic_ev_charging_reference")  # seed references
        _resp = client.get(
            "/v2/workbook?project=generic_ev_charging_reference-reference",
            cookies=cookies)
        assert _resp.status_code == 200 and not _resp.history
        html = _resp.text
        trust_html = html.split('id="assumption-register"')[1].split(
            'id="calculation-trace"')[0]
        for prohibited in ("PPA Base Tariff", "Base Tariff", "PPA Term",
                           "PPA Production Share", "PPA Indexation",
                           "Operating Hours (P50)", "P90", "Merchant Price Curve",
                           "Balancing Cost", "CO2"):
            assert prohibited not in trust_html, prohibited

    def test_ev_register_paths_canonical_but_rows_omitted(self, seeded_db):
        """B: canonical paths stay technology-neutral inside the register;
        the EV view only omits/relabels the DISPLAY rows."""
        from app.model_v2.assumption_register import (
            AssumptionSourceKind,
            RegisterContext,
            build_assumption_register,
        )
        from app.v2.router import _build_assumption_register_view
        from app.v2.ev_labels import apply_ev_register_presentation

        pis = _reference_pis("generic_ev_charging_reference")
        register = build_assumption_register(
            pis.to_projectinputs(),
            RegisterContext.for_working_copy(
                state_provenance=AssumptionSourceKind.USER_INPUT,
                workbook_composite_hash=getattr(pis, "content_hash", None),
            ),
        )
        paths = {e.canonical_path for e in register.entries}
        # canonical identity unchanged — the compat price path still exists
        assert "revenue.ppa_base_tariff" in paths

        view = _build_assumption_register_view(pis)
        view_paths = {r["path"] for r in view["rows"]}
        # hidden compat rows are NOT in the rendered view…
        assert "revenue.ppa_base_tariff" not in view_paths or (
            # …unless relabelled — check the label instead
            next(r["label"] for r in view["rows"]
                 if r["path"] == "revenue.ppa_base_tariff") == "Charging Price"
        )
        for hidden in ("revenue.ppa_production_share",
                       "revenue.market_prices_curve",
                       "revenue.balancing_cost_pv",
                       "revenue.co2_enabled",
                       "technical.operating_hours_p90_10y"):
            assert hidden not in view_paths, hidden

    def test_non_ev_terminology_unchanged(self, seeded_db):
        """G: Solar keeps the technology-neutral register labels."""
        from fastapi.testclient import TestClient
        import main_web
        from app.auth import COOKIE_NAME, create_session_token

        cookies = {COOKIE_NAME: create_session_token(
            user_id="ux-assump-user3", username="admin")}
        client = TestClient(main_web.app, raise_server_exceptions=True)
        _reference_pis("generic_solar_reference")  # seed references
        _resp = client.get(
            "/v2/workbook?project=generic_solar_reference-reference",
            cookies=cookies)
        assert _resp.status_code == 200 and not _resp.history
        html = _resp.text
        trust_html = html.split('id="assumption-register"')[1].split(
            'id="calculation-trace"')[0]
        assert "PPA Base Tariff" in trust_html
        assert "Operating Hours (P50)" in trust_html
        assert "Charging Price" not in trust_html


class TestRegisterZeroTruth:
    def test_legitimate_zero_displays_as_zero(self, seeded_db):
        """F: a canonical 0.0 renders as zero — never as unavailable."""
        from app.v2.router import _build_assumption_register_view
        pis = _reference_pis("generic_solar_reference")
        view = _build_assumption_register_view(pis)
        zero_rows = [r for r in view["rows"] if r["value"] == "0"]
        assert zero_rows, "expected at least one legitimate zero value"
        for row in zero_rows:
            assert row["value"] != "—"
