"""PR #189: typed L2 sequencer authority — OFFICIAL_FEED_NOT_PUBLISHED vs UNREVIEWED.

Robinhood's docs recommend a Chainlink L2 sequencer uptime check, but Chainlink's official sequencer catalog does not publish
a Robinhood Chain feed. No sequencer proxy is invented here. Only an explicit, officially-provenanced
OFFICIAL_FEED_NOT_PUBLISHED review may enable the bounded no-sequencer fallback for this READ-ONLY oracle leg; every other
check stays. Deterministic fixtures only.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.radar_rwa import multi_source_collect as msc
from app.radar_rwa.multi_source_evidence import EvidenceLeg, EvidenceRole, SourceEvidenceStore, oracle_leg
from app.radar_rwa.stock_token_oracle import (
    NO_SEQUENCER_EVIDENCE, SEL_LATEST_ROUND, SEL_ORACLE_PAUSED, read_stock_token_oracle, resolve_sequencer,
    pin_oracle_block,
)
from app.radar_rwa.stock_token_oracle_registry import (
    OracleRegistry, OracleRegistryError, Provenance, SequencerAuthority, SequencerBinding, load_registry,
    parse_registry,
)
from finco_radar.authority.contracts import AuthorityState
from tests.test_multi_source_evidence_v2 import (
    BLOCK_TS, FEED, NOW, NVDA_ID, NVDA_TOKEN, PROV, SEQ, FakeRpc, _pair, binding,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_FILE = ROOT / "app/radar_rwa/data/stock_token_oracle_feeds.json"
NOT_PUBLISHED = "OFFICIAL_FEED_NOT_PUBLISHED"
PROVENANCE = Provenance(**PROV)


def reg(*, authority="not_published", sequencer=None, bindings=None) -> OracleRegistry:
    record = {
        "not_published": SequencerAuthority(NOT_PUBLISHED, 4663, PROVENANCE),
        "unreviewed": SequencerAuthority("UNREVIEWED", 4663, None),
        None: None,
    }[authority]
    items = {b.canonical_id: b for b in (bindings if bindings is not None else [binding()])}
    return OracleRegistry(items, sequencer, record)


def read(rpc=None, registry=None, **kw):
    return read_stock_token_oracle(rpc=rpc or FakeRpc(), registry=registry or reg(), canonical_id=NVDA_ID, as_of=NOW, **kw)


def flatten(obs) -> str:
    return json.dumps({"reason": obs.reason, "evidence": dict(obs.evidence)}, default=str)


# ── 1 / 11. absent sequencer WITHOUT a reviewed absence stays fail-closed ────────────────────────
@pytest.mark.parametrize("authority", [None, "unreviewed"])
def test_sequencer_absent_and_not_reviewed_fails_closed(authority):
    obs = read(registry=reg(authority=authority))
    assert obs.state is AuthorityState.UNAVAILABLE and obs.reason == "ORACLE_SEQUENCER_AUTHORITY_UNAVAILABLE"
    assert obs.value is None


def test_bare_sequencer_null_in_raw_registry_data_is_unreviewed_and_fails_closed():
    raw = {"schema_version": "FINCO_STOCK_TOKEN_ORACLE_FEEDS_V1", "chain_id": 4663, "sequencer": None, "bindings": []}
    registry = parse_registry(raw)
    assert registry.sequencer_authority_state == "UNREVIEWED" and registry.sequencer_authority is None
    bound = OracleRegistry({NVDA_ID: binding()}, registry.sequencer, registry.sequencer_authority)
    assert read(registry=bound).reason == "ORACLE_SEQUENCER_AUTHORITY_UNAVAILABLE"


def test_unreviewed_is_never_honoured_even_if_it_carries_official_provenance():
    registry = OracleRegistry({NVDA_ID: binding()}, None, SequencerAuthority("UNREVIEWED", 4663, PROVENANCE))
    assert registry.sequencer_authority_state == "UNREVIEWED"
    assert read(registry=registry).reason == "ORACLE_SEQUENCER_AUTHORITY_UNAVAILABLE"


def test_a_not_published_record_without_provenance_is_not_honoured():
    registry = OracleRegistry({NVDA_ID: binding()}, None, SequencerAuthority(NOT_PUBLISHED, 4663, None))
    assert registry.sequencer_authority_state == "UNREVIEWED"
    assert read(registry=registry).reason == "ORACLE_SEQUENCER_AUTHORITY_UNAVAILABLE"


# ── 2 / 3 / 4. explicit reviewed absence lets the read continue, honestly ────────────────────────
def test_explicit_official_feed_not_published_lets_the_oracle_read_continue():
    rpc = FakeRpc()
    obs = read(rpc)
    assert obs.state is AuthorityState.AVAILABLE and obs.reason is None and obs.value is not None


def test_explicit_absence_never_queries_a_sequencer_and_never_claims_a_check():
    rpc = FakeRpc()
    obs = read(rpc)
    assert all(to != SEQ for to, _ in rpc.calls)                       # no sequencer feed was read at all
    assert obs.evidence["sequencerChecked"] is False
    assert obs.evidence["sequencerAuthorityState"] == NOT_PUBLISHED
    assert obs.evidence["l2LivenessGuard"] == "PINNED_BLOCK_FRESHNESS_ONLY"
    assert obs.evidence["sequencerGraceProtection"] is False
    for key in ("sequencerFeed", "sequencerAnswer", "sequencerStartedAt", "sequencerGraceSeconds"):
        assert key not in obs.evidence                                   # no fabricated sequencer timestamps


def test_explicit_absence_never_reports_sequencer_ok_or_any_recovery_time():
    text = flatten(read()).upper()
    assert "SEQUENCER_OK" not in text and "SEQUENCER_UP" not in text and "RECOVER" not in text


def test_no_sequencer_status_is_a_documented_constant_and_marks_unchecked():
    ctx = pin_oracle_block(FakeRpc(), as_of=NOW)
    status = resolve_sequencer(FakeRpc(), reg(), ctx)
    assert status.ok and status.checked is False and status.block_hash == ctx.block_hash
    assert dict(status.evidence) == dict(NO_SEQUENCER_EVIDENCE)


# ── 5-9. every other check is unchanged under the explicit absence ───────────────────────────────
def test_stale_pinned_block_still_fails():
    obs = read(FakeRpc(block_ts=int(NOW.timestamp()) - 3600))
    assert obs.state is AuthorityState.UNAVAILABLE and obs.reason == "ORACLE_CHAIN_BLOCK_STALE" and obs.value is None


def test_block_rpc_failure_still_fails():
    assert read(FakeRpc(fail={"block"})).reason == "ORACLE_RPC_UNAVAILABLE"


def test_reorg_or_mismatched_pinned_block_still_fails():
    obs = read(FakeRpc(reorg=True))
    assert obs.state is AuthorityState.UNAVAILABLE and obs.reason == "ORACLE_BLOCK_REORG_OR_MISMATCH" and obs.value is None


def test_oracle_paused_still_fails_and_never_reads_the_round():
    rpc = FakeRpc(paused=1)
    obs = read(rpc)
    assert obs.reason == "ORACLE_CORPORATE_ACTION_PAUSED" and obs.value is None
    assert (FEED, SEL_LATEST_ROUND) not in rpc.calls


def test_pause_state_unreadable_still_fails():
    assert read(FakeRpc(fail={(NVDA_TOKEN, SEL_ORACLE_PAUSED)})).reason == "ORACLE_PAUSE_STATE_UNAVAILABLE"


def test_stale_feed_heartbeat_still_returns_stale():
    obs = read(FakeRpc(updated_at=BLOCK_TS - 86400 - 1))
    assert obs.state is AuthorityState.STALE and obs.reason == "ORACLE_HEARTBEAT_EXCEEDED"
    assert obs.evidence["l2LivenessGuard"] == "PINNED_BLOCK_FRESHNESS_ONLY"      # limitation stays visible on STALE too


def test_missing_reviewed_heartbeat_still_fails_closed():
    assert read(registry=reg(bindings=[binding(heartbeat_seconds=None)])).reason == "ORACLE_HEARTBEAT_NOT_REVIEWED"


@pytest.mark.parametrize("kwargs,reason", [
    ({"answer": 0}, "ORACLE_ANSWER_NOT_POSITIVE"), ({"answer": -1}, "ORACLE_ANSWER_NOT_POSITIVE"),
    ({"updated_at": 0}, "ORACLE_UPDATED_AT_INVALID"), ({"updated_at": BLOCK_TS + 3600}, "ORACLE_UPDATED_AT_IN_FUTURE"),
    ({"round_id": 0}, "ORACLE_ROUND_INCOMPLETE"), ({"answered_in": 1}, "ORACLE_ROUND_INCOMPLETE"),
    ({"description": "AAPL / USD"}, "ORACLE_FEED_DESCRIPTION_MISMATCH"), ({"decimals": 6}, "ORACLE_FEED_DECIMALS_MISMATCH"),
])
def test_invalid_latest_round_data_and_feed_metadata_still_fail(kwargs, reason):
    obs = read(FakeRpc(**kwargs))
    assert obs.state is AuthorityState.UNAVAILABLE and obs.reason == reason and obs.value is None


def test_unreviewed_feed_and_identity_checks_are_untouched():
    assert read(registry=reg(bindings=[])).reason == "ORACLE_FEED_NOT_REVIEWED"
    wrong = binding(token_contract="0x" + "11" * 20)
    assert read(registry=reg(bindings=[wrong])).reason == "ORACLE_BINDING_IDENTITY_MISMATCH"


def test_pinned_block_single_read_and_tag_discipline_still_holds_without_a_sequencer():
    rpc = FakeRpc(advance=True)
    obs = read(rpc)
    assert obs.state is AuthorityState.AVAILABLE
    assert rpc.latest_calls == 1 and rpc.block_reads == ["latest", "0x3e8"]
    assert set(rpc.tags) == {"0x3e8"} and len(rpc.tags) == 4        # paused + description + decimals + latestRoundData


# ── 10. a real source-proven sequencer behaves exactly as before ─────────────────────────────────
def real_sequencer_registry() -> OracleRegistry:
    return OracleRegistry({NVDA_ID: binding()}, SequencerBinding(4663, SEQ, 3600, PROVENANCE), None)


def test_source_proven_sequencer_up_is_checked_and_reported_as_checked():
    rpc = FakeRpc()
    obs = read(rpc, real_sequencer_registry())
    assert obs.state is AuthorityState.AVAILABLE
    assert any(to == SEQ for to, _ in rpc.calls)
    assert obs.evidence["sequencerChecked"] is True and obs.evidence["sequencerAuthorityState"] == "SOURCE_PROVEN"
    assert obs.evidence["sequencerGraceProtection"] is True and "l2LivenessGuard" not in obs.evidence


def test_source_proven_sequencer_down_and_grace_are_unchanged():
    assert read(FakeRpc(seq_answer=1), real_sequencer_registry()).reason == "ORACLE_SEQUENCER_DOWN"
    assert read(FakeRpc(seq_started=BLOCK_TS - 100), real_sequencer_registry()).reason == "ORACLE_SEQUENCER_GRACE_PERIOD"
    assert read(FakeRpc(seq_answer=7), real_sequencer_registry()).reason == "ORACLE_SEQUENCER_AUTHORITY_UNAVAILABLE"


def test_a_bound_sequencer_always_wins_over_any_not_published_record():
    registry = OracleRegistry({NVDA_ID: binding()}, SequencerBinding(4663, SEQ, 3600, PROVENANCE),
                              SequencerAuthority(NOT_PUBLISHED, 4663, PROVENANCE))
    assert registry.sequencer_authority_state == "SOURCE_PROVEN"
    rpc = FakeRpc(seq_answer=1)
    assert read(rpc, registry).reason == "ORACLE_SEQUENCER_DOWN"      # not bypassed by the absence record


# ── registry parsing: explicit, official, consistent, fail closed ────────────────────────────────
def _raw(**authority):
    record = {"state": NOT_PUBLISHED, "chain_id": 4663, "provenance": dict(PROV)}
    record.update(authority)
    return {"schema_version": "FINCO_STOCK_TOKEN_ORACLE_FEEDS_V1", "chain_id": 4663, "sequencer": None,
            "sequencer_authority": record, "bindings": []}


def test_valid_reviewed_absence_parses_to_the_typed_state():
    registry = parse_registry(_raw())
    assert registry.sequencer is None and registry.sequencer_authority_state == NOT_PUBLISHED


@pytest.mark.parametrize("authority,code", [
    ({"state": "NOT_APPLICABLE"}, "ORACLE_SEQUENCER_AUTHORITY_STATE_INVALID"),     # an L2: never "not applicable"
    ({"state": ""}, "ORACLE_SEQUENCER_AUTHORITY_STATE_INVALID"),
    ({"chain_id": 1}, "ORACLE_SEQUENCER_AUTHORITY_CHAIN_INVALID"),
    ({"provenance": None}, "ORACLE_SEQUENCER_AUTHORITY_PROVENANCE_REQUIRED"),
    ({"provenance": {**PROV, "source": "THIRD_PARTY_GITHUB"}}, "ORACLE_SEQUENCER_AUTHORITY_PROVENANCE_NOT_OFFICIAL"),
    ({"provenance": {**PROV, "reference_url": "http://insecure"}}, "ORACLE_SEQUENCER_AUTHORITY_PROVENANCE_URL_REQUIRED"),
    ({"provenance": {**PROV, "reviewed_at": "yesterday"}}, "ORACLE_SEQUENCER_AUTHORITY_PROVENANCE_DATE_INVALID"),
    ({"provenance": {**PROV, "reviewer": ""}}, "ORACLE_SEQUENCER_AUTHORITY_PROVENANCE_REVIEWER_REQUIRED"),
    ({"state": "SOURCE_PROVEN"}, "ORACLE_SEQUENCER_AUTHORITY_CONTRADICTION"),      # claims a proxy that is not bound
])
def test_invalid_sequencer_authority_records_are_rejected(authority, code):
    with pytest.raises(OracleRegistryError, match=code):
        parse_registry(_raw(**authority))


def test_not_published_contradicting_a_bound_proxy_is_rejected():
    raw = _raw()
    raw["sequencer"] = {"chain_id": 4663, "feed_proxy": SEQ, "grace_period_seconds": 3600, "provenance": dict(PROV)}
    with pytest.raises(OracleRegistryError, match="ORACLE_SEQUENCER_AUTHORITY_CONTRADICTION"):
        parse_registry(raw)


def test_explicit_unreviewed_record_parses_and_stays_unreviewed():
    registry = parse_registry(_raw(state="UNREVIEWED", provenance=None))
    assert registry.sequencer_authority_state == "UNREVIEWED"


# ── the shipped registry data ────────────────────────────────────────────────────────────────────
def test_shipped_registry_records_the_reviewed_absence_and_invents_no_address():
    registry = load_registry()
    assert registry.sequencer is None
    assert registry.sequencer_authority_state == NOT_PUBLISHED
    authority = registry.sequencer_authority
    assert authority.provenance.source == "CHAINLINK_OFFICIAL_FEED_CATALOG"
    assert authority.provenance.reference_url == "https://docs.chain.link/data-feeds/l2-sequencer-feeds"
    assert authority.provenance.reviewed_at == "2026-10-04"
    raw = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    assert raw["sequencer"] is None and len(raw["bindings"]) == 8
    # Addresses are expected now: 8 source-proven feed proxies.
    assert len(re.findall(r"0x[0-9a-fA-F]{40}", REGISTRY_FILE.read_text(encoding="utf-8"))) >= 8


def test_shipped_registry_has_eight_source_proven_bindings():
    coverage = load_registry().coverage()
    source_proven = {k for k, v in coverage.items() if v == "SOURCE_PROVEN"}
    not_reviewed = {k for k, v in coverage.items() if v == "ORACLE_FEED_NOT_REVIEWED"}
    assert len(source_proven) == 8
    assert len(not_reviewed) == 5
    assert len(coverage) == 13


# ── cycle + read path ────────────────────────────────────────────────────────────────────────────
def test_cycle_with_reviewed_absence_never_queries_a_sequencer_and_pins_once():
    rpc = FakeRpc(advance=True)
    report = msc.collect_multi_source_once(acquire_asset=_pair, oracle_rpc=rpc, oracle_registry=reg(), as_of=NOW)
    row = next(r for r in report["matrix"] if r["canonical_id"] == NVDA_ID)
    assert row["ORACLE"]["state"] == "AVAILABLE"
    assert rpc.latest_calls == 1 and all(to != SEQ for to, _ in rpc.calls)


def test_cycle_with_unreviewed_authority_keeps_every_bound_oracle_unavailable():
    report = msc.collect_multi_source_once(acquire_asset=_pair, oracle_rpc=FakeRpc(), oracle_registry=reg(authority=None),
                                           as_of=NOW)
    row = next(r for r in report["matrix"] if r["canonical_id"] == NVDA_ID)
    assert row["ORACLE"]["reason"] == "ORACLE_SEQUENCER_AUTHORITY_UNAVAILABLE"
    assert row["MARKET"]["state"] == row["OFFICIAL_REFERENCE"]["state"] == "AVAILABLE"


def test_limitation_is_inspectable_on_the_read_route(tmp_path, monkeypatch):
    from app.radar_ui.r_live_router import router
    path = tmp_path / "evidence.db"
    store = SourceEvidenceStore(path)
    when = datetime.now(timezone.utc) - timedelta(seconds=30)
    obs = read_stock_token_oracle(rpc=FakeRpc(updated_at=int(when.timestamp()) - 5, block_ts=int(when.timestamp())),
                                  registry=reg(), canonical_id=NVDA_ID, as_of=when)
    assert obs.state is AuthorityState.AVAILABLE
    store.append(oracle_leg(NVDA_ID, obs), collected_at=when)
    monkeypatch.setenv("FINCO_SOURCE_EVIDENCE_DB_PATH", str(path))
    app = FastAPI()
    app.include_router(router)
    body = TestClient(app).get(f"/radar/r-live/{NVDA_ID}/evidence").json()
    assert body["sequencer_authority"] == NOT_PUBLISHED
    oracle = body["legs"]["ORACLE"]
    assert oracle["persisted_state"] == "AVAILABLE"
    assert oracle["sequencer_checked"] is False and oracle["l2_liveness_guard"] == "PINNED_BLOCK_FRESHNESS_ONLY"
    assert oracle["sequencer_grace_protection"] is False and oracle["sequencer_authority_state"] == NOT_PUBLISHED


def test_detail_page_states_the_no_sequencer_limitation_next_to_the_oracle():
    page = (ROOT / "app/templates/radar/r_live_detail.html").read_text(encoding="utf-8")
    assert "PINNED_BLOCK_FRESHNESS_ONLY" in page and "no sequencer feed published — chain block freshness only" in page


# ── 12. read-only: no execution / signing / custody path ─────────────────────────────────────────
FORBIDDEN = ("eth_sendTransaction", "eth_sendRawTransaction", "eth_sign", "personal_sign", "signTransaction",
             "private_key", "privateKey", "mnemonic", "send_transaction")


def test_oracle_modules_contain_no_execution_signing_or_custody_path():
    for name in ("stock_token_oracle.py", "stock_token_oracle_registry.py", "multi_source_evidence.py",
                 "multi_source_collect.py"):
        text = (ROOT / "app/radar_rwa" / name).read_text(encoding="utf-8")
        for token in FORBIDDEN:
            assert token not in text, (name, token)


def test_every_rpc_method_used_by_an_oracle_cycle_is_a_read_only_call():
    methods = []

    class Spy(FakeRpc):
        def call(self, method, params):
            methods.append(method)
            return super().call(method, params)

    msc.collect_multi_source_once(acquire_asset=_pair, oracle_rpc=Spy(), oracle_registry=reg(), as_of=NOW)
    assert methods and set(methods) <= {"eth_getBlockByNumber", "eth_call"}
