"""Q4 2026 / Q1 2027 public crypto-roadmap Product Truth contracts.

This suite protects presentation-only roadmap alignment after Yield V1 and
Crypto Utility V1 integration. It deliberately does not test or modify
financial, market, Verify, or entitlement authority implementations.
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


def _section_between(text: str, start_heading: str, end_heading: str) -> str:
    """Slice rendered roadmap by structural section markers, never copy text."""
    start_marker = f'aria-labelledby="{start_heading}"'
    end_marker = f'aria-labelledby="{end_heading}"'
    start_index = text.index(start_marker)
    end_index = text.index(end_marker, start_index)
    return text[start_index:end_index]


def test_primary_product_architecture_is_explicit():
    for rel in ("app/templates/protocol_home.html", "app/templates/protocol_roadmap.html"):
        text = _flat(rel)
        assert "MODEL · RADAR · YIELD · CRYPTO" in text, rel


def test_protocol_layer_is_explicit_and_separate():
    # Manual-QA product-truth correction: the Verified Assets composition
    # surface is removed from the public home (no user workflow, 0 verified
    # production assets); FINCO Verify (/verify) is the public VERIFY
    # surface. The roadmap keeps the historical layer description.
    home = _flat("app/templates/protocol_home.html")
    roadmap = _flat("app/templates/protocol_roadmap.html")
    assert "VERIFY · API · $FINCO" in home, "protocol_home"
    assert 'href="/verified"' not in home, "home must not link the legacy surface"
    assert 'href="/verify"' in home, "home links FINCO Verify"
    assert "VERIFY · API · $FINCO" in roadmap, "protocol_roadmap"
    assert "Verified Assets" in roadmap, "roadmap keeps the layer description"


def test_shared_navigation_exposes_primary_products_and_active_contracts():
    nav = _flat("app/templates/partials/_protocol_nav.html")
    for label, href in (("Model", "/library"), ("Radar", "/radar"),
                        ("Yield", "/yield"), ("Crypto", "/crypto")):
        assert f'href="{href}"' in nav, label
        assert f"> {label} </a>" in nav, label
    assert "proto_active_page == 'yield'" in nav
    assert "proto_active_page == 'crypto'" in nav
    assert 'proto_active_page="yield"' in _flat("app/templates/yield/base.html")
    assert 'proto_active_page="crypto"' in _flat("app/templates/crypto/overview.html")


def test_public_yield_route_is_truthful_when_runtime_is_off(monkeypatch):
    """Primary /yield stays public without turning the Yield runtime on."""
    monkeypatch.delenv("FINCO_YIELD_ENABLED", raising=False)
    monkeypatch.delenv("FINCO_YIELD_EXECUTION_ENABLED", raising=False)

    from fastapi.testclient import TestClient
    import main_web

    response = TestClient(main_web.app, raise_server_exceptions=True).get("/yield")
    assert response.status_code == 200
    text = " ".join(response.text.split())
    assert "FINCO Yield is implemented and feature-gated." in text
    assert "Yield runtime is not enabled in this environment." in text
    assert "Yield execution remains OFF." in text
    assert "No empty opportunity set is inferred" in text
    assert "data-yield-runtime-state=\"disabled\"" in response.text
    assert "<table" not in response.text.lower()


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
        assert "execution is live" not in text.lower()
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
        assert "production token activation is not configured" in text.lower()


def test_roadmap_keeps_execution_off_and_external_delivery_unshipped():
    road = _flat("app/templates/protocol_roadmap.html")
    assert "Yield execution remains OFF" in road or "Yield execution remains separately OFF" in road
    assert "Yield execution: ON" not in road
    assert "execution is live" not in road.lower()
    assert "external alerts are shipped" not in road.lower()
    assert "External alert delivery is NOT SHIPPED" in road


def test_infrastructure_expansion_is_nested_under_model_future_coverage():
    road = _flat("app/templates/protocol_roadmap.html")
    docs = _flat("docs/ROADMAP.md")
    assert "Future Asset Coverage" in road
    assert "Real-World Asset Expansion" in road
    assert "Model future asset coverage" in docs
    assert "Infrastructure vertical expansion remains a Model concern" in road


def test_q4_crypto_native_targets_are_future_not_live():
    road = _flat("app/templates/protocol_roadmap.html")
    live = _section_between(road, "live-heading", "q4-heading")
    q4 = _section_between(road, "q4-heading", "q1-heading")
    for phrase in (
        "External Trade Center",
        "$FINCO Market Surface",
        "RWA Basis / Tokenized Market Monitor",
        "DeFi + RWA Yield",
        "Alert Automation &amp; External Delivery",
    ):
        assert phrase in q4, phrase
        assert phrase not in live, phrase
    assert "Buy / Sell / Swap" in q4
    assert "third-party provider or the user wallet executes" in q4
    assert "No custody" in q4
    assert "no server signing" in q4.lower()
    assert "reference observation is not an executable price" in q4.lower()


def test_q1_programmable_finance_targets_are_future_not_live():
    road = _flat("app/templates/protocol_roadmap.html")
    live = _section_between(road, "live-heading", "q4-heading")
    q1 = _section_between(road, "q1-heading", "later-heading")
    for phrase in (
        "User-Signed Execution",
        "FINCO Wallet Portfolio",
        "FINCO Agent",
        "RWA Collateral & Composability",
        "FINCO Proof / Onchain Attestation",
        "Cross-Chain Routing",
    ):
        assert phrase in q1, phrase
        assert phrase not in live, phrase
    assert "User wallet approval" in q1
    assert "User signature" in q1
    assert "no finco server signing" in q1.lower()
    assert "Signed Run ≠ FINCO Verify ≠ economic truth" in q1
    assert "Radar / Valuation Intelligence" in q1


def test_future_targets_do_not_mutate_current_product_truth():
    road = _flat("app/templates/protocol_roadmap.html")
    assert "production FINCO deployment count = 0" in road
    assert "token gating default = OFF" in road
    assert "Yield execution remains OFF" in road
    assert "In-app Yield Alerts — implemented" in road
    assert "manual Refresh" in road
    assert "background monitoring/scheduler is NOT SHIPPED" in road
    assert "External alert delivery is NOT SHIPPED" in road
    assert "Buy / Sell / Swap" in road
    assert "User-Signed Execution" in road


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
