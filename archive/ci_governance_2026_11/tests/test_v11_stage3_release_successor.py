"""Release qualification and fail-closed proof using real Git objects."""
import json

import pytest

import v11_stage3_release_authority as historical
import v11_stage3_release_successor as successor
from test_v11_stage3_successor import head, mutate, repo, show  # noqa: F401


def test_exact_release_proposal_requires_a_new_owner_decision():
    assert successor.candidate_violations() == []
    record = json.loads((successor.ROOT / successor.RECORD).read_bytes())
    assert record["decision"] == "RELEASE_SUCCESSOR_PENDING_OWNER_REVIEW"
    assert len(record["paths"]) == 13
    assert all(facts["accepted"]["mode"] == "100644" for facts in record["paths"].values())
    assert historical.release_violations(ref=record["anchors"]["historical_release"]["commit"]) == []


@pytest.mark.parametrize("change", ["one-byte", "missing-f01", "new-financial-path", "historical-record", "forged-decision",
                                   "mapping-gap", "old-new-swap", "missing-ancestry", "foreign-sha"])
def test_candidate_rejects_changed_sources_and_authority(repo, tmp_path, head, change):  # noqa: F811
    assert successor.candidate_violations(repo=repo, ref=head) == []
    record = json.loads(show(repo, head, successor.RECORD))
    financial = "financial_engine/dsra/reserve_authority.py"
    changes = {}
    expected = "V11_SUCCESSOR_RECORD_NOT_EXACT"
    if change == "one-byte":
        changes[financial] = show(repo, head, financial) + b"\n"
        expected = "V11_SUCCESSOR_SOURCE_DRIFT"
    elif change == "missing-f01":
        changes[successor.F01] = None
        expected = "V11_SUCCESSOR_SOURCE_DRIFT"
    elif change == "new-financial-path":
        changes["financial_engine/unreviewed.py"] = b"\n"
        expected = "V11_SUCCESSOR_SOURCE_DRIFT"
    elif change == "historical-record":
        changes[historical.RELEASE_PATH] = show(repo, head, historical.RELEASE_PATH) + b"\n"
        expected = "V11_SUCCESSOR_HISTORICAL_RELEASE_CHANGED"
    elif change == "forged-decision":
        record["decision"] = "APPROVED"
    elif change == "mapping-gap":
        del record["paths"][financial]
    elif change == "old-new-swap":
        path = "financial_engine/dsra/target.py"
        facts = record["paths"][path]
        facts["historical"], facts["accepted"] = facts["accepted"], facts["historical"]
    else:
        expected = "V11_SUCCESSOR_FACTS_UNAVAILABLE"
    if change in {"forged-decision", "mapping-gap", "old-new-swap"}:
        changes[successor.RECORD] = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode()
    if change == "foreign-sha":
        ref = "1" * 40
    else:
        ref = mutate(repo, tmp_path, head, changes, orphan=change == "missing-ancestry")
    assert successor.candidate_violations(repo=repo, ref=ref) == [expected]
