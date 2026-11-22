"""Negative controls for the immutable historical stream-scope proofs (tests/stream_scope_proof.py).

The module must prove a HISTORICAL fact about ONE landed stream and must fail closed on any doubt. It must never turn into an exemption: a
stream that really changed a protected path, a tampered range, a missing commit or a non-ancestor of main all produce a non-empty result.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
VENUES_STREAMS = {"test_tokenized_live_intelligence_v1"}
NAMESPACES = ("financial_engine", "finco_core", "domain", "finco_radar/venues")


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True).stdout.strip()


def test_the_module_is_not_an_authority_and_exempts_nothing():
    source = (ROOT / "tests" / "stream_scope_proof.py").read_text(encoding="utf-8")
    for forbidden in ("approved_frozen_path", "released_engine_authority_matches", "unapproved_engine_changes", "strictly_frozen_changes",
                      "ACTIVATION_ENABLED", "rc3_historical_anchor"):
        assert forbidden not in source.replace("# ", ""), forbidden


