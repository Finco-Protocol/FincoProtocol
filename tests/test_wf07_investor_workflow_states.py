"""WF-07 / S7-07: the investor-agreement workspace states Draft / Saved / Incorporated / Historical truthfully and never implies that an agreement
changes Sources & Uses or a committed Run before a canonical Run records it. Presentation only: no funding or waterfall logic."""
from __future__ import annotations

import re
from types import SimpleNamespace as NS

import jinja2
import pytest

ENV = jinja2.Environment(loader=jinja2.FileSystemLoader("app/templates"), autoescape=True)


def _render(*, terms, evidence_agreement, state="CURRENT", history_id=None, editable=True):
    f4 = NS(state=state, editable=editable, history_id=history_id, project_code="p", csrf_token="t", snapshot_id="s", funding=[], history=[],
            unavailable="Investor evidence is unavailable for this Run.", terms=terms,
            evidence=(NS(agreement=evidence_agreement, investors=[]) if evidence_agreement else None),
            context=NS(identity=NS(composite_hash="h"), workspace=NS(active_scenario_name="Base")))
    html = ENV.get_template("v2/partials/_investor_f4.html").render(f4=f4)
    return re.sub(r"\s+", " ", html)


def _workflow(html):
    m = re.search(r'data-testid="f4-workflow-state" data-workflow="([A-Z_]+)">([^<]*)<', html)
    assert m, html[:400]
    return m.group(1), m.group(2)


TERMS = NS(agreement_id="agr-1", version=2, investors=(), contributions=())


def test_no_saved_agreement():
    state, text = _workflow(_render(terms=None, evidence_agreement=None))
    assert state == "NONE" and "No working agreement is saved" in text


def test_saved_but_never_run_is_not_incorporated():
    state, text = _workflow(_render(terms=TERMS, evidence_agreement=None))
    assert state == "SAVED_NOT_RUN" and "has not been incorporated in any canonical Run" in text


def test_saved_newer_than_the_last_run_names_both_versions():
    state, text = _workflow(_render(terms=TERMS, evidence_agreement=NS(agreement_id="agr-1", version=1)))
    assert state == "SAVED_NOT_RUN" and "agr-1 v2 is not yet in a Run" in text and "Last Run used agr-1 v1" in text


def test_incorporated_only_when_version_matches_and_the_run_is_current():
    same = NS(agreement_id="agr-1", version=2)
    assert _workflow(_render(terms=TERMS, evidence_agreement=same, state="CURRENT"))[0] == "INCORPORATED"
    stale = _workflow(_render(terms=TERMS, evidence_agreement=same, state="STALE"))
    assert stale[0] == "INCORPORATED_STALE" and "Run again" in stale[1]


def test_historical_agreement_is_immutable_and_has_no_draft_state():
    html = _render(terms=None, evidence_agreement=NS(agreement_id="agr-1", version=1), state="HISTORICAL", history_id="h1", editable=False)
    state, text = _workflow(html)
    assert state == "HISTORICAL" and "immutable Run" in text and 'data-testid="f4-draft-state"' not in html


def test_the_draft_note_states_that_saving_never_runs_or_changes_a_committed_run():
    html = _render(terms=TERMS, evidence_agreement=None)
    assert 'data-draft="clean"' in html and "never runs the model or changes a committed Run" in html
    assert "does not change Sources &amp; Uses" in html               # ownership percentages vs commitments disclosure preserved
