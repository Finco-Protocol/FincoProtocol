"""FULL L02 oracle (explicit, not autodiscovered: run ``pytest tests/post432_l02_full_oracle.py``). The mandatory subset lives in test_post432_l02_template_rate_percent_v1.py.

Post-#432 live acceptance L02: the template card and the wizard Review state the Senior all-in rate in the same human percent as the created project.

Production evidence: the factory reference templates still store the legacy ratio ``0.055`` (``0.06``) without unit provenance, and the card printed it through a
2-decimal formatter as ``0.06 %`` while the created project held ``5.5`` with ``human_percent_v1``.  The card now shows exactly the value project creation applies
when the factory-reference provenance is proven (the same contract as ``create_working_copy_from_template``), and "Unverified rate unit" otherwise.  Nothing is
guessed from magnitude and no stored rate is changed.  The proofs below run against REAL seeded reference rows in an isolated database (the production legacy state is
reproduced by rewriting those rows to the unmarked ratio), through the real templates endpoint and the real creator."""
from __future__ import annotations

import json

import pytest

from app.input_adapter import RATE_UNIT, RATE_UNIT_KEY
from app.persistence.db import get_cursor
from app.persistence.projects_repository import _compute_baseline_snapshot, get_reference_by_template_source
from app.services.project_library_service import _REFERENCE_DEFINITIONS
from app.v2 import react_projects as P
from tests.test_pr394_staging_corrections_v1 import env  # noqa: F401  (fixture)

KINDS = ("solar", "wind", "data_center", "ev_charging")


def _cards(env):
    return {c["key"]: c for c in env.client.get("/v2/model-react/templates").json()["templates"]}


def _rate_row(card):
    return {a["label"]: a for a in card["starting_assumptions"]}["All-in Interest Rate"]


def _rewrite(record, *, rate, marker, baseline=True, saved=True):
    """Reproduce a stored reference row exactly as production holds it (legacy ratio, no unit marker)."""
    def edit(snapshot):
        snapshot = dict(snapshot)
        snapshot["interest_rate_pct"] = rate
        snapshot.pop(RATE_UNIT_KEY, None)
        if marker:
            snapshot[RATE_UNIT_KEY] = RATE_UNIT
        return snapshot
    with get_cursor() as cur:
        if baseline:
            cur.execute("UPDATE projects SET baseline_snapshot_json=? WHERE project_id=?", (json.dumps(edit(record.baseline_snapshot)), record.project_id))
        if saved:
            cur.execute("SELECT saved_snapshot_json FROM workspace_states WHERE project_id=?", (record.project_id,))
            current = json.loads(cur.fetchone()[0])
            cur.execute("UPDATE workspace_states SET saved_snapshot_json=? WHERE project_id=?", (json.dumps(edit(current)), record.project_id))


def _legacy_state(env):
    _cards(env)                                                         # bootstraps the canonical reference rows
    out = {}
    for kind in KINDS:
        ts = f"generic_{kind}_reference"
        record = get_reference_by_template_source(ts)
        seed = _compute_baseline_snapshot(record.project_type, ts)
        out[kind] = (record, seed, str(float(seed["interest_rate_pct"]) / 100.0))
        _rewrite(record, rate=out[kind][2], marker=False)
    return out


@pytest.mark.parametrize("kind", KINDS)
def test_real_legacy_reference_row_card_equals_created_project(env, kind):
    state = _legacy_state(env)
    record, seed, legacy = state[kind]
    assert legacy in ("0.055", "0.06")                                    # the production values
    stored = get_reference_by_template_source(f"generic_{kind}_reference")
    assert stored.baseline_snapshot["interest_rate_pct"] == legacy and RATE_UNIT_KEY not in stored.baseline_snapshot
    card_rate = _rate_row(_cards(env)[kind])
    created = env.create(kind)                                            # the real creator (create_reference_seeded_project)
    snap = created.baseline_snapshot
    assert snap[RATE_UNIT_KEY] == RATE_UNIT
    assert card_rate == {"label": "All-in Interest Rate", "value": f"{float(snap['interest_rate_pct']):.12g}", "unit": "%"}
    assert float(card_rate["value"]) == float(seed["interest_rate_pct"]) and card_rate["value"] not in ("0.06", "0.055")


def test_the_four_cards_and_the_created_projects_agree_on_unit_and_value(env):
    _legacy_state(env)
    cards = _cards(env)
    for kind in KINDS:
        card_rate = _rate_row(cards[kind])
        snap = env.create(kind).baseline_snapshot
        assert (card_rate["unit"], float(card_rate["value"])) == ("%", float(snap["interest_rate_pct"]))


@pytest.mark.parametrize("value,expected", [("5.5", "5.5"), ("6", "6"), ("0.055", "0.055"), ("0", "0"), (0.12, "0.12"), ("12", "12")])
def test_a_stamped_human_percent_is_shown_unscaled(value, expected):
    assert P._template_rate_percent(None, {"interest_rate_pct": value, RATE_UNIT_KEY: RATE_UNIT}) == expected     # no double scaling


@pytest.mark.parametrize("snapshot", [
    {"interest_rate_pct": "0.055"},                                    # legacy ratio, no provenance, no record
    {"interest_rate_pct": "5.5", RATE_UNIT_KEY: "something_else"},
    {"interest_rate_pct": "abc", RATE_UNIT_KEY: RATE_UNIT},
    {"interest_rate_pct": None, RATE_UNIT_KEY: RATE_UNIT},
    {"interest_rate_pct": "nan", RATE_UNIT_KEY: RATE_UNIT},
    {"interest_rate_pct": "inf", RATE_UNIT_KEY: RATE_UNIT},
    {},
])
def test_an_unprovable_unit_is_never_guessed(snapshot):
    assert P._template_rate_percent(None, snapshot) is None


@pytest.mark.parametrize("tamper", ["foreign_ratio", "origin", "producer", "project_code", "saved_differs", "unknown_marker"])
def test_a_real_record_whose_provenance_breaks_is_unverified(env, tamper):
    state = _legacy_state(env)
    record, seed, legacy = state["solar"]
    if tamper == "foreign_ratio":
        _rewrite(record, rate="0.07", marker=False)
    elif tamper == "saved_differs":
        _rewrite(record, rate="0.07", marker=False, baseline=False)         # creation requires baseline AND the copied snapshot to match
    elif tamper == "unknown_marker":
        with get_cursor() as cur:
            cur.execute("SELECT baseline_snapshot_json FROM projects WHERE project_id=?", (record.project_id,))
            snap = json.loads(cur.fetchone()[0]); snap[RATE_UNIT_KEY] = "something_else"
            cur.execute("UPDATE projects SET baseline_snapshot_json=? WHERE project_id=?", (json.dumps(snap), record.project_id))
    else:
        column = {"origin": "project_origin", "producer": "replay_metadata_json", "project_code": "project_code"}[tamper]
        value = {"origin": "user_created", "producer": "{}", "project_code": "other-code"}[tamper]
        with get_cursor() as cur:
            cur.execute(f"UPDATE projects SET {column}=? WHERE project_id=?", (value, record.project_id))
    row = _rate_row(_cards(env)["solar"])
    assert row == {"label": "All-in Interest Rate", "value": P.RATE_UNVERIFIED, "unit": ""}


def test_the_card_never_rewrites_the_stored_rows(env):
    state = _legacy_state(env)
    before = {k: get_reference_by_template_source(f"generic_{k}_reference").baseline_snapshot for k in KINDS}
    _cards(env)
    assert before == {k: get_reference_by_template_source(f"generic_{k}_reference").baseline_snapshot for k in KINDS}
    assert all(RATE_UNIT_KEY not in s and s["interest_rate_pct"] == state[k][2] for k, s in before.items())


def test_a_stamped_reference_shows_the_stored_percent(env):
    _cards(env)
    for kind in KINDS:
        rate = _rate_row(_cards(env)[kind])
        seed = _compute_baseline_snapshot(get_reference_by_template_source(f"generic_{kind}_reference").project_type, f"generic_{kind}_reference")
        assert rate["unit"] == "%" and float(rate["value"]) == float(seed["interest_rate_pct"])
        assert any(d["template_source"] == f"generic_{kind}_reference" for d in _REFERENCE_DEFINITIONS)
