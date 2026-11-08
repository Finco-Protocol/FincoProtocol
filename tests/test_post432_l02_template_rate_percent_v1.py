"""Post-#432 live acceptance L02: the template card and the wizard Review state the Senior all-in rate in the same human percent as the created project.

Production evidence: the factory reference templates still store the legacy ratio ``0.055`` (``0.06``) without unit provenance, and the card printed it through a
2-decimal formatter as ``0.06 %`` while the created project held ``5.5`` with ``human_percent_v1``.  The card now shows exactly the value project creation applies
when the factory-reference provenance is proven, and "Unverified rate unit" otherwise.  Nothing is guessed from magnitude and no stored rate is changed."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.input_adapter import RATE_UNIT, RATE_UNIT_KEY
from app.persistence.projects_repository import _compute_baseline_snapshot
from app.services.project_library_service import _REFERENCE_DEFINITIONS
from app.v2 import react_projects as P


def _factory_record(definition, rate_text):
    return SimpleNamespace(template_source=definition["template_source"], project_type=definition["project_type"], project_code=definition["project_code"],
                           project_origin="factory_template", replay_metadata={"reference": True, "factory": definition["factory"]}), {"interest_rate_pct": rate_text}


@pytest.mark.parametrize("definition", _REFERENCE_DEFINITIONS, ids=lambda d: d["template_source"])
def test_a_proven_legacy_ratio_template_shows_the_percent_creation_applies(definition):
    seed = _compute_baseline_snapshot(definition["project_type"], definition["template_source"])["interest_rate_pct"]
    legacy = str(float(seed) / 100.0)
    record, snapshot = _factory_record(definition, legacy)
    shown = P._template_rate_percent(record, snapshot)
    assert shown == f"{float(seed):.12g}" and float(shown) >= 1.0, (shown, legacy)      # 5.5 / 6, never 0.06 or 0.055
    assert shown != "0.06"


@pytest.mark.parametrize("value,expected", [("5.5", "5.5"), ("6", "6"), ("0.055", "0.055"), ("0", "0"), (0.12, "0.12"), ("12", "12")])
def test_a_stamped_human_percent_is_shown_unscaled(value, expected):
    assert P._template_rate_percent(None, {"interest_rate_pct": value, RATE_UNIT_KEY: RATE_UNIT}) == expected     # no double scaling


@pytest.mark.parametrize("snapshot", [
    {"interest_rate_pct": "0.055"},                                    # legacy ratio, no provenance, no record
    {"interest_rate_pct": "5.5", RATE_UNIT_KEY: "something_else"},
    {"interest_rate_pct": "abc", RATE_UNIT_KEY: RATE_UNIT},
    {"interest_rate_pct": None, RATE_UNIT_KEY: RATE_UNIT},
    {"interest_rate_pct": "nan", RATE_UNIT_KEY: RATE_UNIT},
    {},
])
def test_an_unprovable_unit_is_never_guessed(snapshot):
    assert P._template_rate_percent(None, snapshot) is None


def test_a_factory_record_with_a_foreign_ratio_is_unverified():
    definition = _REFERENCE_DEFINITIONS[0]
    record, snapshot = _factory_record(definition, "0.07")              # does not equal the trusted seed ratio
    assert P._template_rate_percent(record, snapshot) is None
    record.replay_metadata = {}
    seed = _compute_baseline_snapshot(definition["project_type"], definition["template_source"])["interest_rate_pct"]
    assert P._template_rate_percent(record, {"interest_rate_pct": str(float(seed) / 100.0)}) is None   # producer provenance missing


def test_the_card_row_carries_the_percent_unit_or_the_unverified_text(monkeypatch):
    from app.workbook.input_set import ProjectInputSet
    definition = next(d for d in _REFERENCE_DEFINITIONS if d["template_source"] == "generic_solar_reference")
    seed = _compute_baseline_snapshot(definition["project_type"], definition["template_source"])
    legacy = dict(seed, interest_rate_pct=str(float(seed["interest_rate_pct"]) / 100.0))
    legacy.pop(RATE_UNIT_KEY, None)
    record, _ = _factory_record(definition, None)
    row = [a for a in P._starting_assumptions("solar", legacy, record) if a["label"] == "All-in Interest Rate"][0]
    assert row == {"label": "All-in Interest Rate", "value": f"{float(seed['interest_rate_pct']):.12g}", "unit": "%"}
    unverified = [a for a in P._starting_assumptions("solar", legacy, None) if a["label"] == "All-in Interest Rate"][0]
    assert unverified["value"] == P.RATE_UNVERIFIED and unverified["unit"] == ""


from tests.test_pr394_staging_corrections_v1 import env  # noqa: E402,F401  (fixture)


def test_the_templates_endpoint_agrees_with_the_created_project(env):
    cards = {c["key"]: c for c in env.client.get("/v2/model-react/templates").json()["templates"]}
    for key in ("solar", "wind", "data_center", "ev_charging"):
        rows = {a["label"]: a for a in cards[key]["starting_assumptions"]}
        rate = rows["All-in Interest Rate"]
        assert rate["unit"] == "%" and float(rate["value"]) >= 1.0, (key, rate)
        definition = next(d for d in _REFERENCE_DEFINITIONS if d["template_source"] == f"generic_{key}_reference")
        seed = _compute_baseline_snapshot(definition["project_type"], definition["template_source"])
        assert float(rate["value"]) == float(seed["interest_rate_pct"])
