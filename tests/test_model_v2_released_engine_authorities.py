"""Released Model V2 engine authorities (release-candidate governance closure).

The temporary epic scope marker is deleted at the release candidate. The two
reviewed canonical financial-statement engine files are then covered by an explicit,
exact-path, content-pinned, code-level rule — never a wildcard, never a marker.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import model_v2_governance as gov
from finance_integrity_governance import unapproved_engine_changes

REPO = Path(__file__).resolve().parents[1]
ASSEMBLY = "financial_engine/financial_statements/assembly.py"
CONTRACTS = "financial_engine/financial_statements/contracts.py"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, check=True).stdout


def test_exactly_the_two_reviewed_files_no_wildcards():
    assert set(gov.RELEASED_MODEL_V2_ENGINE_AUTHORITIES) == {ASSEMBLY, CONTRACTS}
    for path, blob in gov.RELEASED_MODEL_V2_ENGINE_AUTHORITIES.items():
        assert "*" not in path and not path.endswith("/")
        assert path.startswith(gov.ENGINE_PREFIX)
        assert len(blob) == 40 and set(blob) <= set("0123456789abcdef")


def test_repository_carries_the_exact_reviewed_content():
    for path, blob in gov.RELEASED_MODEL_V2_ENGINE_AUTHORITIES.items():
        assert _git(REPO, "rev-parse", f"HEAD:{path}").strip() == blob, path
        assert gov.released_engine_authority_matches(path)


def test_exemption_is_independent_of_any_scope_marker(monkeypatch):
    monkeypatch.setattr(gov, "active_scope", lambda: None)
    assert gov.approved_by_active_model_v2_scope(ASSEMBLY)
    assert gov.approved_by_active_model_v2_scope(CONTRACTS)
    assert unapproved_engine_changes([ASSEMBLY, CONTRACTS]) == []


def test_every_other_engine_path_stays_frozen(monkeypatch):
    monkeypatch.setattr(gov, "active_scope", lambda: None)
    for other in ("financial_engine/tax/atad.py", "financial_engine/orchestrator.py",
                  "financial_engine/financial_statements/other.py",
                  "financial_engine/financial_statements/assembly.py.bak"):
        assert not gov.approved_by_active_model_v2_scope(other), other
    assert unapproved_engine_changes([ASSEMBLY, "financial_engine/tax/atad.py"]) == [
        "financial_engine/tax/atad.py"]
    assert gov.model_v2_unapproved_engine_changes(["financial_engine/tax/atad.py"]) == [
        "financial_engine/tax/atad.py"]


def test_frozen_core_and_hard_deny_namespaces_are_never_released(monkeypatch):
    monkeypatch.setattr(gov, "active_scope", lambda: None)
    for path in ("finco_core/inputs/x.py", "finco_radar/venues/registry.py",
                 "finco_yield/access.py", "app/radar_rwa/stock_token_oracle.py",
                 "app/crypto_access.py", "domain/analytics/x.py"):
        assert not gov.approved_by_active_model_v2_scope(path), path


def test_a_further_edit_of_a_released_file_is_unauthorized_again(tmp_path):
    """Content pin: same path, different content -> no exemption."""
    repo = tmp_path / "r"
    (repo / "financial_engine/financial_statements").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "finco-test")
    _git(repo, "config", "user.name", "Finco Test")
    (repo / ASSEMBLY).write_text("# later unreviewed edit\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "x")
    assert not gov.released_engine_authority_matches(ASSEMBLY, repo=repo)
    assert not gov.approved_by_active_model_v2_scope(ASSEMBLY, repo=repo)


def test_unreadable_blob_fails_closed(tmp_path):
    assert not gov.released_engine_authority_matches(ASSEMBLY, repo=tmp_path / "missing")
    assert not gov.released_engine_authority_matches(ASSEMBLY, ref="no-such-ref-xyz")


def test_permanent_hard_deny_still_wins_over_the_released_rule(monkeypatch):
    monkeypatch.setattr(gov, "RELEASED_MODEL_V2_ENGINE_AUTHORITIES",
                        {"finco_radar/venues/registry.py": "0" * 40})
    assert not gov.approved_by_active_model_v2_scope("finco_radar/venues/registry.py")
