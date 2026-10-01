"""Q4 2026 / Q1 2027 public crypto-roadmap Product Truth contracts.

This suite protects the presentation-only roadmap alignment after Yield V1 and
Crypto Utility V0 merged. It deliberately does not test or modify financial,
market, Verify, or entitlement authority implementations.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BASE_SHA = "347812cca574a73c64bc71e29296204b3e144cfc"


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _flat(rel: str) -> str:
    return " ".join(_read(rel).split())


def test_primary_product_architecture_is_explicit():
    for rel in ("app/templates/protocol_home.html", "app/templates/protocol_roadmap.html"):
        text = _flat(rel)
        assert "MODEL · RADAR · YIELD · CRYPTO" in text, rel


def test_protocol_layer_is_explicit_and_separate():
    for rel in ("app/templates/protocol_home.html", "app/templates/protocol_roadmap.html"):
        text = _flat(rel)
        assert "VERIFY · API · $FINCO" in text, rel
        assert "Verified Assets" in text, rel


def test_roadmap_has_live_q4_q1_later_bands():
    road = _flat("app/templates/protocol_roadmap.html")
    for phrase in ("LIVE / IMPLEMENTED", "Q4 2026", "Q1 2027", "LATER"):
        assert phrase in road, phrase


def test_yield_truth_after_pr148_merge():
    road = _flat("app/templates/protocol_roadmap.html")
    docs = _flat("docs/ROADMAP.md")
    for text in (road, docs):
        assert "FINCO Yield" in text
        assert "FINCO_YIELD_EXECUTION_ENABLED" in text
        assert "defaults OFF" in text or "default = OFF" in text
        assert "no server signing" in text.lower()
        assert "no automatic broadcast" in text.lower()
        assert "no FINCO-owned vault" in text
        assert "External alert delivery" in text or "external alert delivery" in text
        assert "NOT SHIPPED" in text
    assert "PR #148, not merged" not in road


def test_finco_activation_truth_is_fail_closed():
    road = _flat("app/templates/protocol_roadmap.html")
    docs = _flat("docs/ROADMAP.md")
    for text in (road, docs):
        assert "production FINCO deployment count = 0" in text or "production approved `$FINCO` deployment count = **0**" in text
        assert "token gating default = OFF" in text or "token gating default = **OFF**" in text
        assert "production threshold = UNSET" in text or "production threshold = **UNSET**" in text
        assert "chain = UNSET" in text or "production chain = **UNSET**" in text
        assert "token contract = UNSET" in text or "production token contract = **UNSET**" in text


def test_roadmap_does_not_claim_execution_or_alert_delivery_live():
    road = _flat("app/templates/protocol_roadmap.html")
    assert "execution is live" not in road.lower()
    assert "external alerts are shipped" not in road.lower()
    assert "external alert delivery is NOT SHIPPED" in road
    assert "Yield execution remains OFF" in road or "Yield execution remains separately OFF" in road


def test_infrastructure_expansion_is_nested_under_model_future_coverage():
    road = _flat("app/templates/protocol_roadmap.html")
    docs = _flat("docs/ROADMAP.md")
    assert "Future Asset Coverage" in road
    assert "Model future asset coverage" in docs
    assert "Infrastructure vertical expansion remains a Model concern" in road


def test_frozen_authority_namespaces_unchanged_from_canonical_base():
    frozen = (
        "financial_engine/",
        "finco_core/",
        "finco_radar/authority/",
        "app/model_validation/",
        "app/verified/",
        "app/protocol/entitlement_evaluator.py",
        "app/protocol/entitlement_policy.py",
        "app/protocol/token_deployments.py",
        "finco_yield/access.py",
    )
    probe = subprocess.run(
        ["git", "diff", "--name-only", f"{BASE_SHA}..HEAD"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        return
    changed = [line.strip() for line in probe.stdout.splitlines() if line.strip()]
    for path in changed:
        assert not any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in frozen), path
