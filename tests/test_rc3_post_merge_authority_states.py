"""Post-RC-3 main: the three financial-authority states stay apart (see tests/rc3_authority_states.py). Adds no approval."""
import ast
import copy
import subprocess
from pathlib import Path

import pytest

import model_v2_governance as governance
from tests import rc3_authority_states as S
from tests import m7_rc3_candidate_successor as M7

ROOT = Path(__file__).resolve().parent.parent
HISTORICAL_MAPS = ("WF07_REVENUE_AUTHORITIES", "F3_5_A_JUNIOR_AUTHORITIES", "REVENUE_V2_ADVANCED_AUTHORITIES",
                   "REVENUE_V3_CANDIDATE_AUTHORITIES", "DEVELOPER_ECONOMICS_V1_AUTHORITIES", "F3_2_4_FINANCING_AUTHORITIES",
                   "F3_1_CONTRACT_AUTHORITIES", "WF04_NUMERIC_PRECISION_AUTHORITIES", "RELEASED_MODEL_V2_ENGINE_AUTHORITIES")


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def _map_at(ref, name):
    tree = ast.parse(_git("show", f"{ref}:tests/model_v2_governance.py"))
    for node in tree.body:
        target = node.targets[0] if isinstance(node, ast.Assign) else getattr(node, "target", None)
        if isinstance(target, ast.Name) and target.id == name and getattr(node, "value", None) is not None:
            return ast.literal_eval(node.value)
    return None


def test_the_historical_checkpoint_is_the_accepted_rc2_merge():
    parents = _git("rev-list", "--parents", "-n", "1", S.historical_checkpoint()).split()[1:]
    assert S.historical_checkpoint() == "6fc77de98bc0562fb51efdbf96e1803a29b5b148"
    assert parents == ["5058c6b4935168241d6923676cb32955cb903185", "2155a76bfff4acc3a4e15f7cf35012933ce1a10c"]


@pytest.mark.parametrize("name", HISTORICAL_MAPS)
def test_no_historical_pin_map_was_rewritten_by_rc3(name):
    """Every released pin map is byte-for-byte what it was at the checkpoint: M7 was never written into a released map."""
    at_checkpoint = _map_at(S.historical_checkpoint(), name)
    assert at_checkpoint is not None, name
    assert getattr(governance, name) == at_checkpoint
    for blob in M7.M7_RC3_CANDIDATE_AUTHORITIES.values():
        assert blob not in at_checkpoint.values()


def test_the_central_governance_files_are_byte_identical_to_the_checkpoint():
    for name in ("model_v2_governance.py", "finance_integrity_governance.py", "radar_authority_governance.py"):
        assert _git("hash-object", f"tests/{name}").strip() == _git("rev-parse", f"{S.historical_checkpoint()}:tests/{name}").strip(), name


def test_the_three_states_are_distinct_and_activation_is_unreachable_for_m7():
    states = {S.HISTORICAL_RELEASED, S.INTEGRATED_RELEASE_CLOSED_CANDIDATE, S.ACTIVATED_FINANCIAL_AUTHORITY, S.UNAUTHORIZED}
    assert len(states) == 4
    reached = {S.authority_state(p) for p in M7.M7_RC3_CANDIDATE_AUTHORITIES}
    assert reached <= {S.INTEGRATED_RELEASE_CLOSED_CANDIDATE, S.HISTORICAL_RELEASED}
    assert S.ACTIVATED_FINANCIAL_AUTHORITY not in reached
    source = (ROOT / "tests/rc3_authority_states.py").read_text(encoding="utf-8")
    assert source.count("return ACTIVATED_FINANCIAL_AUTHORITY") == 0


def test_every_m7_blob_is_the_candidate_state_while_the_flags_are_closed():
    assert S.release_closed_violations() == []
    m7_only = [p for p in M7.M7_RC3_CANDIDATE_AUTHORITIES if p.startswith(M7.FROZEN_PREFIXES)]
    for path in m7_only:
        state = S.authority_state(path)
        assert state in (S.INTEGRATED_RELEASE_CLOSED_CANDIDATE, S.HISTORICAL_RELEASED), (path, state)
        if state == S.HISTORICAL_RELEASED:                      # never true for M7's blobs: no released map contains them
            raise AssertionError(f"{path} is unexpectedly in a released map")


@pytest.mark.parametrize("flag_path,name", sorted(S.RELEASE_FLAGS.items()))
def test_an_opened_release_flag_removes_the_candidate_state(flag_path, name, tmp_path):
    """A candidate with an opened flag is UNAUTHORIZED, not 'more approved'."""
    repo = tmp_path / "r"
    repo.mkdir()
    for args in (["init"], ["config", "core.autocrlf", "false"], ["config", "user.name", "Synthetic"],
                 ["config", "user.email", "noreply@users.noreply.github.com"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    def put(path, data):
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    for path in S.RELEASE_FLAGS:
        put(path, f"{S.RELEASE_FLAGS[path]} = False\n".encode())
    put(S.MANIFEST, b'{"release_approved": false}\n')
    sample = "financial_engine/bess.py"
    put(sample, subprocess.run(["git", "show", f"HEAD:{sample}"], cwd=ROOT, capture_output=True, check=True).stdout)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "closed"], cwd=repo, check=True, capture_output=True)
    assert S.release_closed_violations(repo=repo) == []
    put(flag_path, f"{name} = True\n".encode())
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "opened"], cwd=repo, check=True, capture_output=True)
    assert S.release_closed_violations(repo=repo)
    assert S.authority_state(sample, repo=repo) == S.UNAUTHORIZED
    put(S.MANIFEST, b'{"release_approved": true}\n')
    put(flag_path, f"{name} = False\n".encode())
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "forged manifest"], cwd=repo, check=True, capture_output=True)
    assert any("manifest" in p for p in S.release_closed_violations(repo=repo))


def test_unknown_financial_authority_and_missing_acceptance_stay_fail_closed():
    for path in ("financial_engine/never_reviewed.py", "finco_core/never_reviewed.py", "domain/never_reviewed.py"):
        assert S.authority_state(path) == S.UNAUTHORIZED
    facts = M7.collect()
    assert facts["record"] is None
    assert any("APPROVAL_REQUIRED" in p for p in M7.acceptance_violations(facts))
    assert M7.current_acceptance_granted() is False
    forged = copy.deepcopy(facts)
    forged["source_head_ancestor"] = False
    assert M7.content_violations(forged)
