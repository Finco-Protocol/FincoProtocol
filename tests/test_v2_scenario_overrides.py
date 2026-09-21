"""Model Parity Pass — V2 scenario override editing tests.

Covers the new POST /v2/workbook/scenarios/update-overrides endpoint and the
overrides field added to ScenarioPresentation.

Priority gaps addressed (gap audit finding #1):
  A. Base Case rejection — endpoint returns 409 for base-case scenarios
  B. Valid override persistence — endpoint calls update_scenario_overrides and
     returns 200 + re-rendered scenario list partial
  C. Auth gate — 401 without authenticated user
  D. Project/scenario guard — 404 for unknown project or scenario
  E. Protected reference gate — 409 for protected reference projects
  F. Non-numeric field skipped — non-parseable value silently dropped (not 500)
  G. Missing required params — 422 when project or scenario_id absent
  H. Persistence failure — 500 when update_scenario_overrides returns None
  I. HTMX response — HTML partial returned for HX-Request: true
  J. Non-HTMX redirect — 303 redirect for non-HTMX requests

  Presentation layer:
  K. ScenarioPresentation carries overrides dict from ScenarioRecord
  L. Base Case scenario has empty overrides in presentation
  M. Override editor fields constant is exported from scenario_presentation
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


# ─── helpers ─────────────────────────────────────────────────────────────────


def _get_test_client():
    from fastapi.testclient import TestClient
    from app.v2.router import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router, prefix="/v2")
    return TestClient(app, raise_server_exceptions=False)


def _mock_user(user_id="user-sc"):
    return SimpleNamespace(user_id=user_id)


def _make_project_record(is_protected=False):
    rec = SimpleNamespace(
        project_id="proj-id-1",
        project_code="test_proj",
        project_name="Test Project",
        project_type="wind",
        project_origin="user_created",
        template_source=None,
        baseline_snapshot=None,
        full_inputs=None,
        is_reference_project=is_protected,
    )
    return rec


def _make_scenario(is_base_case=False, overrides=None):
    return SimpleNamespace(
        scenario_id="sc-1",
        project_id="proj-id-1",
        scenario_name="Downside",
        is_base_case=is_base_case,
        archived=False,
        overrides=overrides or {},
        base_input_set={},
        snapshot=None,
        last_run_summary={},
        updated_at=None,
    )


def _make_ws():
    return SimpleNamespace(
        active_scenario_id="sc-1",
        active_scenario_name="Downside",
        last_runtime_snapshot_id=None,
        dirty=False,
    )


def _post_overrides(client, data, htmx=True, follow_redirects=True):
    headers = {"HX-Request": "true"} if htmx else {}
    return client.post(
        "/v2/workbook/scenarios/update-overrides",
        data=data,
        headers=headers,
        follow_redirects=follow_redirects,
    )


# ─── Case A: base-case rejection ─────────────────────────────────────────────


def test_update_overrides_base_case_rejected():
    """Case A: base-case scenario returns 409."""
    client = _get_test_client()
    base_sc = _make_scenario(is_base_case=True)

    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user()),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(_make_project_record(), "user-sc"),
        ),
        patch("app.persistence.scenarios_repository.get_scenario", return_value=base_sc),
    ):
        resp = _post_overrides(client, {"project": "test_proj", "scenario_id": "sc-1"})

    assert resp.status_code == 409
    body = resp.json()
    assert "Base Case" in body.get("error", "")


# ─── Case B: valid override persistence ──────────────────────────────────────


def test_update_overrides_success_persists_and_returns_html():
    """Case B: valid overrides are persisted; response is HTML (re-rendered partial)."""
    client = _get_test_client()
    sc = _make_scenario(overrides={})
    updated_sc = _make_scenario(overrides={"tariff_eur_mwh": 55.0})

    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user()),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(_make_project_record(), "user-sc"),
        ),
        patch("app.persistence.scenarios_repository.get_scenario", return_value=sc),
        patch(
            "app.persistence.scenarios_repository.update_scenario_overrides",
            return_value=updated_sc,
        ) as mock_upo,
        patch(
            "app.persistence.workspace_repository.get_workspace_state",
            return_value=_make_ws(),
        ),
        patch(
            "app.persistence.scenarios_repository.list_scenarios",
            return_value=[updated_sc],
        ),
    ):
        resp = _post_overrides(
            client,
            {"project": "test_proj", "scenario_id": "sc-1", "tariff_eur_mwh": "55"},
        )

    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    # Verify persistence was called with the correct numeric override
    mock_upo.assert_called_once_with("user-sc", "sc-1", {"tariff_eur_mwh": 55.0})


# ─── Case C: auth gate ────────────────────────────────────────────────────────


def test_update_overrides_unauthenticated():
    """Case C: missing auth returns 401."""
    client = _get_test_client()
    with patch("app.v2.router._get_current_user", return_value=None):
        resp = _post_overrides(client, {"project": "test_proj", "scenario_id": "sc-1"})
    assert resp.status_code == 401


# ─── Case D: project / scenario guard ────────────────────────────────────────


def test_update_overrides_project_not_found():
    """Case D1: unknown project returns 404."""
    client = _get_test_client()
    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user()),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(None, "user-sc"),
        ),
    ):
        resp = _post_overrides(client, {"project": "ghost", "scenario_id": "sc-1"})
    assert resp.status_code == 404


def test_update_overrides_scenario_not_found():
    """Case D2: unknown scenario_id returns 404."""
    client = _get_test_client()
    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user()),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(_make_project_record(), "user-sc"),
        ),
        patch("app.persistence.scenarios_repository.get_scenario", return_value=None),
    ):
        resp = _post_overrides(client, {"project": "test_proj", "scenario_id": "ghost"})
    assert resp.status_code == 404


def test_update_overrides_scenario_wrong_project():
    """Case D3: scenario belongs to different project → 404."""
    client = _get_test_client()
    sc_wrong = _make_scenario()
    sc_wrong = SimpleNamespace(**{**sc_wrong.__dict__, "project_id": "other-proj"})

    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user()),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(_make_project_record(), "user-sc"),
        ),
        patch("app.persistence.scenarios_repository.get_scenario", return_value=sc_wrong),
    ):
        resp = _post_overrides(client, {"project": "test_proj", "scenario_id": "sc-1"})
    assert resp.status_code == 404


# ─── Case E: protected reference gate ────────────────────────────────────────


def test_update_overrides_protected_reference_rejected():
    """Case E: protected reference project → 409."""
    client = _get_test_client()

    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user()),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(_make_project_record(is_protected=True), "user-sc"),
        ),
        patch("app.v2.router.is_protected_reference", return_value=True),
    ):
        resp = _post_overrides(client, {"project": "ref_proj", "scenario_id": "sc-1"})
    assert resp.status_code == 409


# ─── Case F: non-numeric field silently skipped ───────────────────────────────


def test_update_overrides_non_numeric_value_skipped():
    """Case F: non-numeric value for a field is silently dropped; other fields proceed."""
    client = _get_test_client()
    sc = _make_scenario()
    updated_sc = _make_scenario(overrides={"gearing_pct": 70.0})

    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user()),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(_make_project_record(), "user-sc"),
        ),
        patch("app.persistence.scenarios_repository.get_scenario", return_value=sc),
        patch(
            "app.persistence.scenarios_repository.update_scenario_overrides",
            return_value=updated_sc,
        ) as mock_upo,
        patch(
            "app.persistence.workspace_repository.get_workspace_state",
            return_value=_make_ws(),
        ),
        patch("app.persistence.scenarios_repository.list_scenarios", return_value=[updated_sc]),
    ):
        resp = _post_overrides(
            client,
            {
                "project": "test_proj",
                "scenario_id": "sc-1",
                "tariff_eur_mwh": "not_a_number",  # dropped
                "gearing_pct": "70",                # kept
            },
        )

    assert resp.status_code == 200
    # Only the numeric field reaches the persistence layer
    mock_upo.assert_called_once_with("user-sc", "sc-1", {"gearing_pct": 70.0})


# ─── Case G: missing required params ─────────────────────────────────────────


def test_update_overrides_missing_project():
    """Case G1: missing project field → 422."""
    client = _get_test_client()
    with patch("app.v2.router._get_current_user", return_value=_mock_user()):
        resp = _post_overrides(client, {"scenario_id": "sc-1"})
    assert resp.status_code == 422


def test_update_overrides_missing_scenario_id():
    """Case G2: missing scenario_id field → 422."""
    client = _get_test_client()
    with patch("app.v2.router._get_current_user", return_value=_mock_user()):
        resp = _post_overrides(client, {"project": "test_proj"})
    assert resp.status_code == 422


# ─── Case H: persistence failure ─────────────────────────────────────────────


def test_update_overrides_persistence_failure():
    """Case H: update_scenario_overrides returns None → 500."""
    client = _get_test_client()
    sc = _make_scenario()

    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user()),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(_make_project_record(), "user-sc"),
        ),
        patch("app.persistence.scenarios_repository.get_scenario", return_value=sc),
        patch(
            "app.persistence.scenarios_repository.update_scenario_overrides",
            return_value=None,
        ),
    ):
        resp = _post_overrides(
            client,
            {"project": "test_proj", "scenario_id": "sc-1", "tariff_eur_mwh": "50"},
        )
    assert resp.status_code == 500


# ─── Case I: HTMX response ───────────────────────────────────────────────────


def test_update_overrides_htmx_response_contains_scenario_list():
    """Case I: HTMX request → HTML partial with v2-sheet-scenarios element."""
    client = _get_test_client()
    sc = _make_scenario(overrides={"tariff_eur_mwh": 50.0})
    updated_sc = _make_scenario(overrides={"tariff_eur_mwh": 55.0})

    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user()),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(_make_project_record(), "user-sc"),
        ),
        patch("app.persistence.scenarios_repository.get_scenario", return_value=sc),
        patch(
            "app.persistence.scenarios_repository.update_scenario_overrides",
            return_value=updated_sc,
        ),
        patch(
            "app.persistence.workspace_repository.get_workspace_state",
            return_value=_make_ws(),
        ),
        patch("app.persistence.scenarios_repository.list_scenarios", return_value=[updated_sc]),
    ):
        resp = _post_overrides(
            client,
            {"project": "test_proj", "scenario_id": "sc-1", "tariff_eur_mwh": "55"},
            htmx=True,
        )

    assert resp.status_code == 200
    assert "v2-sheet-scenarios" in resp.text


# ─── Case J: non-HTMX redirect ───────────────────────────────────────────────


def test_update_overrides_non_htmx_redirects():
    """Case J: non-HTMX request → 303 redirect to workbook page."""
    client = _get_test_client()
    sc = _make_scenario()
    updated_sc = _make_scenario(overrides={"gearing_pct": 65.0})

    with (
        patch("app.v2.router._get_current_user", return_value=_mock_user()),
        patch(
            "app.persistence.projects_repository.resolve_accessible_project",
            return_value=(_make_project_record(), "user-sc"),
        ),
        patch("app.persistence.scenarios_repository.get_scenario", return_value=sc),
        patch(
            "app.persistence.scenarios_repository.update_scenario_overrides",
            return_value=updated_sc,
        ),
        patch(
            "app.persistence.workspace_repository.get_workspace_state",
            return_value=_make_ws(),
        ),
        patch("app.persistence.scenarios_repository.list_scenarios", return_value=[updated_sc]),
    ):
        resp = _post_overrides(
            client,
            {"project": "test_proj", "scenario_id": "sc-1", "gearing_pct": "65"},
            htmx=False,
            follow_redirects=False,
        )

    assert resp.status_code == 303
    assert "test_proj" in resp.headers.get("location", "")


# ─── Case K: ScenarioPresentation carries overrides ──────────────────────────


def test_scenario_presentation_carries_overrides():
    """Case K: build_scenario_presentation exposes overrides from ScenarioRecord."""
    from app.v2.scenario_presentation import build_scenario_presentation

    sc = _make_scenario(overrides={"tariff_eur_mwh": 55.0, "gearing_pct": 70.0})
    pres = build_scenario_presentation(sc, active_scenario_id=None)

    assert pres.overrides == {"tariff_eur_mwh": 55.0, "gearing_pct": 70.0}


def test_scenario_presentation_no_overrides_returns_empty_dict():
    """Case K2: scenario with no overrides → empty dict, not None."""
    from app.v2.scenario_presentation import build_scenario_presentation

    sc = _make_scenario(overrides={})
    pres = build_scenario_presentation(sc, active_scenario_id=None)

    assert pres.overrides == {}
    assert isinstance(pres.overrides, dict)


# ─── Case L: base case has empty overrides ────────────────────────────────────


def test_scenario_presentation_base_case_empty_overrides():
    """Case L: base-case scenario always has empty overrides in presentation."""
    from app.v2.scenario_presentation import build_scenario_presentation

    base_sc = _make_scenario(is_base_case=True, overrides={})
    pres = build_scenario_presentation(base_sc, active_scenario_id=None)

    assert pres.is_base_case is True
    assert pres.overrides == {}


# ─── Case M: OVERRIDE_EDITOR_FIELDS constant ─────────────────────────────────


def test_override_editor_fields_exported():
    """Case M: OVERRIDE_EDITOR_FIELDS constant is importable and well-formed."""
    from app.v2.scenario_presentation import OVERRIDE_EDITOR_FIELDS

    assert len(OVERRIDE_EDITOR_FIELDS) >= 4  # at least revenue + debt fields
    for entry in OVERRIDE_EDITOR_FIELDS:
        key, label, unit = entry
        assert key and label and unit
        assert isinstance(key, str)


def test_override_editor_fields_cover_key_modellable_inputs():
    """Case M2: key financial modelling fields are in the editor field list."""
    from app.v2.scenario_presentation import OVERRIDE_EDITOR_FIELDS

    keys = {entry[0] for entry in OVERRIDE_EDITOR_FIELDS}
    # Revenue
    assert "tariff_eur_mwh" in keys
    assert "p50_hours" in keys
    # Costs
    assert "opex_y1_keur" in keys
    # Debt
    assert "gearing_pct" in keys
    assert "interest_rate_pct" in keys


# ─── Correction A: HTML attribute safety (A1 regression) ─────────────────────
#
# These tests render the sheet_scenarios.html template through Jinja2 directly
# and verify that:
#  1. The Edit and Rename buttons do NOT embed raw JSON in onclick attributes.
#  2. The data-* attributes are present and correctly encoded.
#  3. Python's html.parser decodes the attributes to the original Python values.
#  4. JSON.parse on the recovered data-overrides works (via json.loads proxy).
#  5. Adversarial scenario names containing double-quotes and & survive intact.


def _render_scenarios_partial(scenarios, active_scenario_id=None, project_code="proj"):
    """Render sheet_scenarios.html via Jinja2 (same loader as the V2 router)."""
    import os
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    template_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app", "templates", "v2",
    )
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("partials/sheet_scenarios.html")
    return template.render(
        scenarios=scenarios,
        active_scenario_id=active_scenario_id,
        project_code=project_code,
        ws=None,
    )


def _parse_buttons(html_text, btn_class_fragment):
    """Parse HTML and return list of attribute dicts for matching buttons."""
    from html.parser import HTMLParser

    class ButtonCollector(HTMLParser):
        def __init__(self):
            super().__init__()
            self.buttons = []

        def handle_starttag(self, tag, attrs):
            if tag == "button":
                attr_dict = dict(attrs)
                cls = attr_dict.get("class", "")
                if btn_class_fragment in cls:
                    self.buttons.append(attr_dict)

    collector = ButtonCollector()
    collector.feed(html_text)
    return collector.buttons


def test_a1_edit_button_uses_data_attributes_not_onclick_json():
    """A1: Edit button must NOT embed raw JSON in onclick; must use data-* attrs."""
    from app.v2.scenario_presentation import build_scenario_presentation

    sc = _make_scenario(overrides={"tariff_eur_mwh": 45.0, "gearing_pct": 60.0})
    pres = build_scenario_presentation(sc, active_scenario_id=None)
    html = _render_scenarios_partial([pres])

    edit_btns = _parse_buttons(html, "v2-scenario-action-btn--edit")
    assert edit_btns, "Edit button not found in rendered HTML"
    btn = edit_btns[0]

    # data-* attributes must be present
    assert "data-scenario-id" in btn, "data-scenario-id missing"
    assert "data-scenario-name" in btn, "data-scenario-name missing"
    assert "data-overrides" in btn, "data-overrides missing"

    # onclick must NOT contain raw JSON (no { before ) )
    onclick = btn.get("onclick", "")
    assert "FromButton(this)" in onclick, "onclick should call FromButton(this)"

    # data-overrides must be valid JSON (html.parser decodes &#34; → ")
    import json
    recovered = json.loads(btn["data-overrides"])
    assert recovered.get("tariff_eur_mwh") == 45.0
    assert recovered.get("gearing_pct") == 60.0


def test_a1_rename_button_uses_data_attributes_not_onclick_json():
    """A1: Rename button must NOT embed raw JSON in onclick; must use data-* attrs."""
    from app.v2.scenario_presentation import build_scenario_presentation

    sc = _make_scenario(overrides={})
    pres = build_scenario_presentation(sc, active_scenario_id=None)
    html = _render_scenarios_partial([pres])

    rename_btns = _parse_buttons(html, "v2-scenario-action-btn--rename")
    assert rename_btns, "Rename button not found in rendered HTML"
    btn = rename_btns[0]

    assert "data-scenario-id" in btn, "data-scenario-id missing on Rename"
    assert "data-scenario-name" in btn, "data-scenario-name missing on Rename"

    onclick = btn.get("onclick", "")
    assert "FromButton(this)" in onclick, "Rename onclick should call FromButton(this)"
    # Must NOT contain tojson-style string (no JS string literal with JSON double-quote)
    assert '{"' not in onclick and '"}' not in onclick, "Rename onclick embeds raw JSON"


def test_a1_edit_button_scenario_name_round_trips():
    """A1: scenario name is HTML-safe in data attribute and recovers exactly."""
    from app.v2.scenario_presentation import build_scenario_presentation

    sc = _make_scenario(overrides={"tariff_eur_mwh": 45.0, "gearing_pct": 60.0})
    pres = build_scenario_presentation(sc, active_scenario_id=None)
    html = _render_scenarios_partial([pres])

    edit_btns = _parse_buttons(html, "v2-scenario-action-btn--edit")
    assert edit_btns
    assert edit_btns[0]["data-scenario-name"] == "Downside"


def test_a1_adversarial_scenario_name_with_quotes_and_ampersand():
    """A1 adversarial: scenario name containing double-quotes and & survives intact.

    Scenario name: Downside "P90" & Debt
    This would break a tojson-in-onclick attribute; must work with data-* attrs.
    """
    from app.v2.scenario_presentation import build_scenario_presentation, ScenarioPresentation

    adversarial_name = 'Downside "P90" & Debt'
    sc = SimpleNamespace(
        scenario_id="sc-adv",
        scenario_name=adversarial_name,
        is_base_case=False,
        archived=False,
        overrides={"tariff_eur_mwh": 45.0, "gearing_pct": 60.0},
        base_input_set={},
        snapshot=None,
        last_run_summary={},
        updated_at=None,
    )
    pres = build_scenario_presentation(sc, active_scenario_id=None)
    html = _render_scenarios_partial([pres])

    # HTML must parse without errors (html.parser tolerates broken attrs but we
    # verify the button's decoded data-scenario-name matches exactly)
    edit_btns = _parse_buttons(html, "v2-scenario-action-btn--edit")
    assert edit_btns, "Edit button not rendered for adversarial scenario"
    btn = edit_btns[0]

    # html.parser decodes &amp; → & and &quot; / &#34; → "
    assert btn["data-scenario-name"] == adversarial_name, (
        f"Scenario name round-trip failed: got {btn['data-scenario-name']!r}"
    )

    # data-overrides must still parse as JSON
    import json
    recovered = json.loads(btn["data-overrides"])
    assert recovered.get("tariff_eur_mwh") == 45.0


def test_a1_override_modal_values_prefill():
    """A1 modal interaction: data-overrides JSON contains the expected field values.

    This proves that when JavaScript calls JSON.parse(btn.dataset.overrides),
    it recovers the correct tariff and gearing values for pre-filling the form.
    """
    from app.v2.scenario_presentation import build_scenario_presentation
    import json

    overrides = {"tariff_eur_mwh": 45.0, "gearing_pct": 60.0}
    sc = _make_scenario(overrides=overrides)
    pres = build_scenario_presentation(sc, active_scenario_id=None)
    html = _render_scenarios_partial([pres])

    edit_btns = _parse_buttons(html, "v2-scenario-action-btn--edit")
    assert edit_btns
    btn = edit_btns[0]

    # Simulate what JavaScript does: JSON.parse(btn.dataset.overrides)
    recovered = json.loads(btn["data-overrides"])

    # Tariff pre-fill value
    assert recovered.get("tariff_eur_mwh") == 45.0, \
        f"Tariff not pre-filled correctly: {recovered.get('tariff_eur_mwh')!r}"
    # Gearing pre-fill value
    assert recovered.get("gearing_pct") == 60.0, \
        f"Gearing not pre-filled correctly: {recovered.get('gearing_pct')!r}"


def test_a1_html_is_parseable_without_attribute_breakage():
    """A1: rendered HTML must not have broken attributes due to unescaped JSON quotes.

    If the attribute were broken (old onclick pattern), html.parser would report
    fewer attributes than expected because the attribute would be split at the
    first unescaped double-quote.
    This test confirms the HTML is well-formed at the attribute level.
    """
    from app.v2.scenario_presentation import build_scenario_presentation
    from html.parser import HTMLParser

    sc = _make_scenario(overrides={"tariff_eur_mwh": 45.0, "gearing_pct": 60.0})
    pres = build_scenario_presentation(sc, active_scenario_id=None)
    html = _render_scenarios_partial([pres])

    class OnclickCollector(HTMLParser):
        def __init__(self):
            super().__init__()
            self.edit_onclick = None

        def handle_starttag(self, tag, attrs):
            if tag == "button":
                attr_dict = dict(attrs)
                cls = attr_dict.get("class", "")
                if "v2-scenario-action-btn--edit" in cls:
                    self.edit_onclick = attr_dict.get("onclick", "")

    collector = OnclickCollector()
    collector.feed(html)

    assert collector.edit_onclick is not None, "Edit button not parsed"
    # The entire onclick value must be a single clean function call — not broken JSON
    assert "FromButton(this)" in collector.edit_onclick
    # Must not look like an old broken onclick with raw JSON object literal
    assert "{" not in collector.edit_onclick, (
        f"Edit onclick still embeds object literal: {collector.edit_onclick!r}"
    )
