"""F03 exact-source successor: positive identity, tamper, mode and history refusals."""
import json
import subprocess
from pathlib import Path

from tests import f03_financing_scope as F

ROOT = Path(__file__).resolve().parents[1]

def _git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode().strip()

def test_f03_immutable_base_and_exact_source_registration():
    d = F.manifest()
    assert d and set(d["source_blobs"]) == F.OWNED_PATHS
    assert set(d["base_blobs"]) == F.SUPERSEDED
    assert _git("rev-parse", F.BASE + "^{tree}") == F.BASE_TREE
    assert F.signature_ok() and F.exact_blobs_ok()
    assert F.reviewed_handoff_ok(F.ROOT, None, F.REGISTRY)
    assert F.reviewed_handoff_ok(F.ROOT, None, F.L_MODULE)
    assert F.CI_PATHS == frozenset((".github/workflows/finval_f01_acceptance.yml",))
    assert not any(p.startswith(F.FORBIDDEN) and p not in F.CI_PATHS for p in F.OWNED_PATHS)
    assert F.reviewed_workflow_ok()
    assert F.MAP_KEYS == (F.REGISTRY, "static/react/finco-react.js")

def test_f03_current_maps_are_only_the_two_moved_pins():
    pins = F.manifest()["source_blobs"]
    for p in F.CURRENT_MAPS:
        old = json.loads(_git("show", F.BASE + ":" + p))
        current = json.loads((ROOT / p).read_text())
        assert set(old) == set(current)
        assert all(old[k] == current[k] for k in old if k != "source_blobs")
        assert set(old["source_blobs"]) == set(current["source_blobs"])
        changed = {k for k in old["source_blobs"] if old["source_blobs"][k] != current["source_blobs"][k]}
        assert changed <= set(F.MAP_KEYS)
        for k in changed:
            assert current["source_blobs"][k] == pins[k]


def test_f03_f01_workflow_is_exactly_the_reviewed_45_minute_successor():
    old = _git("show", F.BASE + ":" + F.CI_WORKFLOW)
    current = (ROOT / F.CI_WORKFLOW).read_text()
    reviewed = old
    for before, after in F.WORKFLOW_EDITS:
        assert reviewed.count(before) == 1
        reviewed = reviewed.replace(before, after)
    assert reviewed == current
    assert "    timeout-minutes: 45\n" in current
    assert "    timeout-minutes: 25\n" in old
    assert "assert len(cases)==20" in current
    assert "assert len([c for c in cases if c.get('classname','').endswith('finval_f01_browser_acceptance')]) == 4" in current
    assert current.count("--durations=20") == 2
    assert F.reviewed_workflow_ok()


def test_f03_f01_workflow_tamper_is_rejected_even_with_other_valid_sources():
    current = (ROOT / F.CI_WORKFLOW).read_bytes()
    assert F.reviewed_workflow_ok(actual=current)
    for bad in (
        current + b"\\n# unexpected CI-policy change\\n",
        current.replace(b"timeout-minutes: 45", b"timeout-minutes: 450", 1),
        current.replace(b"assert len(cases)==20", b"assert len(cases)>=0", 1),
        current.replace(b"docker build -f docs/ci_v3/phase4/runtime/Dockerfile", b"docker build -f Dockerfile", 1),
    ):
        assert bad != current
        assert not F.reviewed_workflow_ok(actual=bad)
