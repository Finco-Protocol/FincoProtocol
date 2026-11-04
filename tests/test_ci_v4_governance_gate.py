"""CI V4 central governance gate: verdict logic with stub cohorts (fast). The real one-pass gate runs on the exact tree in the CI V4
static job on every PR; these tests prove it fails closed on a non-exact cohort, an unregistered set, a false composite, a mutation
violation or any error."""
import json
import types

import pytest

from tools import ci_v4_governance_gate as G


def _stub(monkeypatch, *, exact=(True, True), composite=True, violations=(), successor=True, registered=None):
    from tests import fin_v2_cohorts as C
    from tests import model_mutation_security_successor as S
    mods = [types.SimpleNamespace(__name__="c%d" % i, exact_blobs_ok=(lambda v=v: v)) for i, v in enumerate(exact)]
    monkeypatch.setattr(C, "cohorts", lambda: mods)
    monkeypatch.setattr(C, "COHORT_MODULES", tuple(registered if registered is not None else [m.__name__ for m in mods]))
    monkeypatch.setattr(C, "valid", lambda *a, **k: composite)
    monkeypatch.setattr(S, "BLOBS", {})
    monkeypatch.setattr(S, "violations", lambda src: list(violations))
    monkeypatch.setattr(S, "current_mutation_successor_valid", lambda *a, **k: successor)


def _run(tmp_path):
    out = tmp_path / "g.json"
    rc = G.main(["--output", str(out)])
    return rc, json.loads(out.read_text())


def test_all_exact_passes(tmp_path, monkeypatch):
    _stub(monkeypatch)
    rc, rec = _run(tmp_path)
    assert rc == 0 and rec["verdict"] == "PASS"


@pytest.mark.parametrize("kw", [dict(exact=(True, False)), dict(composite=False), dict(violations=("x: unreviewed blob",)),
                                dict(successor=False), dict(registered=["c0", "c1", "c2"]), dict(exact=())])
def test_any_gap_fails_closed(tmp_path, monkeypatch, kw):
    _stub(monkeypatch, **kw)
    rc, rec = _run(tmp_path)
    assert rc == 1 and rec["verdict"] == "FAIL"


def test_an_error_fails_closed(tmp_path, monkeypatch):
    from tests import fin_v2_cohorts as C
    monkeypatch.setattr(C, "cohorts", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    rc, rec = _run(tmp_path)
    assert rc == 1 and "boom" in rec["error"]
