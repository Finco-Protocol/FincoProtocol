"""Negative checks for proposed, not yet independently approved, M6 successor."""
from copy import deepcopy
import pytest
from m6_exact_content_successor import (
    M6_EXACT_BLOBS, M6_CHANGED_PATHS, M6_VALIDATOR_SITES,
    current_m6_successor_valid, violations, ROOT,
)

def _facts():
    return dict(ancestry=True, changed=set(M6_CHANGED_PATHS),
                blobs=dict(M6_EXACT_BLOBS), sites=set(M6_VALIDATOR_SITES),
                economics=(ROOT / "app/model_v2/acquisition/economics.py").read_text(),
                router=(ROOT / "app/v2/acquisition_router.py").read_text())

def test_exact_current_m6_candidate_is_only_a_proposal():
    assert current_m6_successor_valid()
    assert violations(**_facts()) == []

def test_every_pinned_blob_mutation_or_omission_denied():
    for path in M6_EXACT_BLOBS:
        f = _facts()
        f["blobs"][path] = "0" * 40
        assert violations(**f), path
        f = _facts()
        del f["blobs"][path]
        assert violations(**f), path

@pytest.mark.parametrize("path", [
    "app/v2/unreviewed_writer.py", "app/persistence/new_run_writer.py",
    "financial_engine/unreviewed.py", "app/model_v2/acquisition/rogue.py",
    "app/trust_readiness/registry.py", "tests/test_trust_readiness_unknown.py",
])
def test_unknown_changed_path_denied(path):
    f = _facts()
    f["changed"].add(path)
    assert violations(**f)

def test_changed_financial_flag_or_historical_provenance_denied():
    f = _facts()
    f["economics"] = f["economics"].replace("ACTIVATION_ENABLED = False", "ACTIVATION_ENABLED = True", 1)
    assert violations(**f)
    f = _facts()
    f["ancestry"] = False
    assert violations(**f)

def test_unknown_state_changing_route_and_csrf_inventory_denied():
    f = _facts()
    f["router"] += "\n" + chr(64) + "router.post('/valuation-acquisition/rogue')\nasync def rogue(): pass\n"
    assert violations(**f)
    f = _facts()
    f["sites"].add("app/v2/rogue.py")
    assert violations(**f)
    f = _facts()
    f["sites"].remove("app/v2/acquisition_router.py")
    assert violations(**f)
