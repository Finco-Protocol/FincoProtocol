"""Historical pins and rejection behavior survive separately reviewed successors."""
import ast
from pathlib import Path
import subprocess

import pytest

import model_v2_governance as governance
from finance_integrity_governance import approved_frozen_path, strictly_frozen_changes, unapproved_engine_changes

BASE = "76b7215baf9dfe02d83382d6c33d01559eba9641"
REPO = Path(__file__).resolve().parents[1]

APPROVED = {
    "financial_engine/book_basis.py": "1281cc05a5638714e78279968ee739d9af2cfc02",
    "financial_engine/financial_statements/assembly.py": "778610e8bb5c2a61b022f147a601cc0f02d66982",
    "financial_engine/financial_statements/contracts.py": "f5a15655d58b1d4a5ac7c02f0cdde5bc2a069358",
    "financial_engine/financing/generic_product_policy.py": "2894334e7241c4ac9f8967d4ce4ca6ce77a32fa0",
    "financial_engine/financing/junior_debt.py": "2205cfbcca33889975c964a5748797c82af5792f",
    "financial_engine/financing/project.py": "30536cec8779fdb6a490d82fd80bfce2c09e16fe",
    "financial_engine/financing/project_uses.py": "489cbcc800158326a5b3764aef25514b6ad6ab48",
    "financial_engine/project_returns/contracts.py": "2a43b4e82db2fa6eee956970c5a5c6087245b36f",
    "financial_engine/project_returns/model.py": "711bf15d954c5e20cce13fd6df1067e5d00182e2",
    "financial_engine/senior_debt/project_adapter.py": "a73611a117f0c04ecc7bd7350eac64456520f265",
    "financial_engine/shareholder_waterfall/contracts.py": "19cff0f003a9fdf8921cae8e5c18e703d93e2408",
    "financial_engine/shareholder_waterfall/model.py": "e3473e1a2064c8310e41b434da2b0aff9d5753b8",
    "finco_core/inputs/_models.py": "b896d3c071ee22c1c82c48f23d4c169e058c7a7b",
    "finco_core/inputs/junior_debt.py": "ef63e3355f30541a69b503a3a2e2c02feaf1803f",
    "finco_core/inputs/serialization.py": "31f70570376b2f5b50ece583c54c1d9811e90a3c",
}


def historical_authorities():
    original = subprocess.run(["git", "show", f"{BASE}:tests/model_v2_governance.py"],
        cwd=REPO, capture_output=True, check=True).stdout.decode("utf-8-sig")
    maps = {}
    for node in ast.parse(original).body:
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        else:
            continue
        for name in names:
            if name.endswith("_AUTHORITIES"):
                maps[name] = ast.literal_eval(node.value)
    return maps


HISTORICAL_AUTHORITIES = historical_authorities()


def test_only_fifteen_independently_accepted_blobs_are_released():
    assert governance.F3_5_A_JUNIOR_AUTHORITIES == APPROVED
    from rc7b_quarterly_candidate_authority import RC7B_CANDIDATE_AUTHORITIES, superseded_by_gate_r
    for path, blob in APPROVED.items():
        current = subprocess.run(["git", "rev-parse", f"HEAD:{path}"], cwd=REPO,
            capture_output=True, text=True, check=True).stdout.strip()
        if superseded_by_gate_r(path, repo=governance.REPO):
            # RC-7B: only under an ACTIVE Gate R (signed record + authentic independent review + exact twelve blobs) does a superseding candidate
            # replace the historical pin. Release-closed candidate only: never the released pin, never an approved frozen path.
            assert current == RC7B_CANDIDATE_AUTHORITIES[path], path
            assert not governance.released_engine_authority_matches(path)
            assert not approved_frozen_path(path)
            continue
        assert current == blob, path
        assert governance.released_engine_authority_matches(path)
        assert approved_frozen_path(path)
    from rc7b_quarterly_candidate_authority import without_gate_r_superseded
    assert without_gate_r_superseded(unapproved_engine_changes(list(APPROVED)), repo=governance.REPO) == []
    assert strictly_frozen_changes(list(APPROVED)) == []


@pytest.mark.parametrize("name", ["RELEASED_MODEL_V2_ENGINE_AUTHORITIES", "DEVELOPER_ECONOMICS_V1_AUTHORITIES",
    "F3_1_CONTRACT_AUTHORITIES", "F3_2_4_FINANCING_AUTHORITIES", "WF04_NUMERIC_PRECISION_AUTHORITIES",
    "WF07_REVENUE_AUTHORITIES"])
def test_exact_historical_authority_maps_are_preserved(name):
    assert getattr(governance, name) == HISTORICAL_AUTHORITIES[name]


@pytest.mark.parametrize("path", ["finco_core/inputs/unapproved_candidate.py",
    "financial_engine/financing/unapproved_candidate.py", "financial_engine/financing/junior_debt.py.extra",
    "finco_core/inputs/junior_debt.py/extra", "finco_radar/unapproved_candidate.py"])
def test_unrelated_paths_have_no_release_authority(path):
    assert not governance.released_engine_authority_matches(path)
    assert not governance.approved_by_active_model_v2_scope(path)
    assert not approved_frozen_path(path)
    if path.startswith("financial_engine/"):
        assert unapproved_engine_changes([path]) == [path]
    elif path.startswith(("finco_core/", "finco_radar/")):
        assert strictly_frozen_changes([path]) == [path]


@pytest.mark.parametrize("path,blob", sorted(set(
    item for name in ("F3_1_CONTRACT_AUTHORITIES", "F3_2_4_FINANCING_AUTHORITIES",
        "WF04_NUMERIC_PRECISION_AUTHORITIES", "WF07_REVENUE_AUTHORITIES")
    for item in HISTORICAL_AUTHORITIES[name].items()) | set(APPROVED.items())))
def test_changed_financial_blobs_and_missing_refs_cannot_reuse_historical_pin(tmp_path, monkeypatch, path, blob):
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)
    git("init")
    git("config", "core.autocrlf", "false")
    target = tmp_path / path
    target.parent.mkdir(parents=True)
    original = subprocess.run(["git", "cat-file", "blob", blob], cwd=REPO, capture_output=True, check=True).stdout
    target.write_bytes(original)
    git("add", path)
    git("-c", "user.name=Synthetic Governance", "-c", "user.email=noreply@users.noreply.github.com", "commit", "-m", "Synthetic reviewed content")
    assert governance.released_engine_authority_matches(path, repo=tmp_path)
    target.write_bytes(original + b"\n# Synthetic unauthorized alteration.\n")
    git("add", path)
    git("-c", "user.name=Synthetic Governance", "-c", "user.email=noreply@users.noreply.github.com", "commit", "-m", "Synthetic unapproved content")
    assert not governance.released_engine_authority_matches(path, repo=tmp_path)
    assert not governance.released_engine_authority_matches(path, repo=tmp_path, ref="missing-review-ref")
    assert governance.released_engine_authority_matches(path, repo=tmp_path, ref="HEAD~1")
    monkeypatch.setattr(governance, "REPO", tmp_path)
    assert not approved_frozen_path(path)
    assert not governance.approved_by_active_model_v2_scope(path, ref="missing-review-ref")
    if path.startswith("financial_engine/"):
        assert unapproved_engine_changes([path]) == [path]
    elif path.startswith(("finco_core/", "finco_radar/")):
        assert strictly_frozen_changes([path]) == [path]


def test_candidate_release_is_closed():
    from app.workbook.junior_debt_config import ACTIVATION_ENABLED
    assert ACTIVATION_ENABLED is False
