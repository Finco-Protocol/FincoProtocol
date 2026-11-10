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
    assert not any(p.startswith(F.FORBIDDEN) for p in F.OWNED_PATHS)
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
