"""PR #189 Correction A: sequencer-authority continuity at read time + auditable authority-context dedupe.

Persisted rows are immutable. The CURRENT reviewed sequencer authority may preserve or degrade a persisted ORACLE row but
never upgrade it, and a row is only usable if its RECORDED liveness context is compatible with the current authority. The
ORACLE digest includes the authority context (not poll-specific block metadata) so a materially different context appends.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from decimal import Decimal

import pytest

from app.radar_rwa.multi_source_evidence import (
    EvidenceLeg, EvidenceRole, SourceEvidenceStore, oracle_leg, read_latest_legs_readonly,
)
from app.radar_rwa.stock_token_oracle import (
    NO_SEQUENCER_EVIDENCE, SEL_LATEST_ROUND, read_stock_token_oracle,
)
from app.radar_rwa.stock_token_oracle_registry import (
    OracleRegistry, Provenance, SequencerAuthority, SequencerBinding,
)
from finco_radar.authority.contracts import AuthorityState
from tests.test_multi_source_evidence_v2 import (
    BLOCK_TS, NOW, NVDA_ID, PROV, SEQ, FakeRpc, binding, word,
)

SEQ2 = "0x" + "5f" * 20
PROVENANCE = Provenance(**PROV)
READ_AT = NOW + timedelta(seconds=60)          # inside the 24h feed heartbeat of the fixtures


def seq_extra(address: str, *, started: int = BLOCK_TS - 86400) -> dict:
    return {(address, SEL_LATEST_ROUND): "0x" + word(1) + word(0) + word(started) + word(started) + word(1)}


def reg_not_published(**binding_kw) -> OracleRegistry:
    return OracleRegistry({NVDA_ID: binding(**binding_kw)}, None,
                          SequencerAuthority("OFFICIAL_FEED_NOT_PUBLISHED", 4663, PROVENANCE))


def reg_source_proven(proxy: str = SEQ, grace: int = 3600, **binding_kw) -> OracleRegistry:
    return OracleRegistry({NVDA_ID: binding(**binding_kw)}, SequencerBinding(4663, proxy, grace, PROVENANCE), None)


def reg_unreviewed() -> OracleRegistry:
    return OracleRegistry({NVDA_ID: binding()}, None, None)


def collect(registry: OracleRegistry, **rpc_kw) -> EvidenceLeg:
    """Collect an oracle leg with the REAL oracle reader under ``registry`` (so the recorded context is genuine)."""
    extra = {**seq_extra(SEQ), **seq_extra(SEQ2), **rpc_kw.pop("extra", {})}
    obs = read_stock_token_oracle(rpc=FakeRpc(extra=extra, **rpc_kw), registry=registry, canonical_id=NVDA_ID, as_of=NOW)
    assert obs.state is AuthorityState.AVAILABLE, obs.reason
    return oracle_leg(NVDA_ID, obs)


@pytest.fixture()
def store(tmp_path):
    return SourceEvidenceStore(tmp_path / "evidence.db")


def dump(store):
    with sqlite3.connect(store.path) as conn:
        return conn.execute("SELECT * FROM source_evidence ORDER BY seq").fetchall()


def read_under(store, current: OracleRegistry, when=READ_AT) -> dict:
    return read_latest_legs_readonly(NVDA_ID, path=store.path, now=when, oracle_registry=current)["legs"]["ORACLE"]


def persisted(store, registry: OracleRegistry, **kw) -> list:
    store.append(collect(registry, **kw), collected_at=NOW)
    return dump(store)


def raw_row(store, payload: dict | None, *, state="AVAILABLE", ts=None):
    ts = ts or (NOW - timedelta(seconds=65)).isoformat()
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "INSERT INTO source_evidence (digest, canonical_id, canonical_asset_id, evidence_role, source_authority, "
            "source_instrument, value, unit, source_timestamp, collected_at, state, reason, payload) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"raw-{state}-{len(dump(store))}", NVDA_ID, "NVDA", "ORACLE", "SRC", "inst", "190", "USD", ts,
             NOW.isoformat(), state, None, json.dumps(payload if payload is not None else {})))


# ── read-time authority transitions ──────────────────────────────────────────────────────────────
def test_fallback_row_stays_available_while_the_official_absence_stands_and_other_checks_pass(store):
    before = persisted(store, reg_not_published())
    out = read_under(store, reg_not_published())
    assert out["state"] == "AVAILABLE" and out["reason"] is None
    assert out["sequencer_checked"] is False and out["l2_liveness_guard"] == "PINNED_BLOCK_FRESHNESS_ONLY"
    assert dump(store) == before


def test_fallback_row_becomes_unavailable_when_current_authority_is_unreviewed(store):
    before = persisted(store, reg_not_published())
    out = read_under(store, reg_unreviewed())
    assert out["state"] == "UNAVAILABLE" and out["reason"] == "ORACLE_SEQUENCER_AUTHORITY_UNAVAILABLE"
    assert out["persisted_state"] == "AVAILABLE"                       # history untouched, presentation degraded
    assert dump(store) == before


def test_current_unreviewed_beats_a_fresh_valid_feed_and_a_valid_heartbeat(store):
    persisted(store, reg_source_proven())
    out = read_under(store, reg_unreviewed())
    assert out["state"] == "UNAVAILABLE" and out["reason"] == "ORACLE_SEQUENCER_AUTHORITY_UNAVAILABLE"


def test_unreviewed_outranks_a_stale_heartbeat_too(store):
    persisted(store, reg_not_published())
    late = NOW + timedelta(seconds=86400 + 600)
    assert read_under(store, reg_unreviewed(), late)["reason"] == "ORACLE_SEQUENCER_AUTHORITY_UNAVAILABLE"
    assert read_under(store, reg_not_published(), late)["state"] == "STALE"          # heartbeat still enforced otherwise


def test_old_fallback_row_is_rejected_once_a_real_sequencer_binding_exists(store):
    before = persisted(store, reg_not_published())
    out = read_under(store, reg_source_proven())
    assert out["state"] == "UNAVAILABLE" and out["reason"] == "ORACLE_SEQUENCER_EVIDENCE_POLICY_MISMATCH"
    assert out["persisted_state"] == "AVAILABLE" and dump(store) == before


def test_compatible_source_proven_row_remains_available_with_the_same_sequencer(store):
    persisted(store, reg_source_proven())
    out = read_under(store, reg_source_proven())
    assert out["state"] == "AVAILABLE" and out["reason"] is None
    assert out["sequencer_checked"] is True and out["sequencer_authority_state"] == "SOURCE_PROVEN"
    assert out["sequencer_grace_protection"] is True


def test_source_proven_row_with_a_rotated_sequencer_proxy_fails_closed(store):
    persisted(store, reg_source_proven(SEQ))
    out = read_under(store, reg_source_proven(SEQ2))
    assert out["state"] == "UNAVAILABLE" and out["reason"] == "ORACLE_SEQUENCER_EVIDENCE_POLICY_MISMATCH"


def test_source_proven_row_checked_under_a_different_grace_policy_fails_closed(store):
    persisted(store, reg_source_proven(grace=3600))
    assert read_under(store, reg_source_proven(grace=7200))["reason"] == "ORACLE_SEQUENCER_EVIDENCE_POLICY_MISMATCH"


def test_source_proven_row_cannot_stand_under_a_current_official_absence_record(store):
    persisted(store, reg_source_proven())
    assert read_under(store, reg_not_published())["reason"] == "ORACLE_SEQUENCER_EVIDENCE_POLICY_MISMATCH"


@pytest.mark.parametrize("current", [reg_not_published, reg_source_proven])
def test_row_without_sequencer_metadata_fails_closed_when_current_policy_requires_it(store, current):
    raw_row(store, {"heartbeatSeconds": 86400})                 # a fresh row that never recorded its liveness context
    out = read_under(store, current())
    assert out["state"] == "UNAVAILABLE" and out["reason"] == "ORACLE_SEQUENCER_EVIDENCE_MISSING"


@pytest.mark.parametrize("override", [
    {"sequencerChecked": True},                                # claims a check that "official absence" never performs
    {"sequencerGraceProtection": True},
    {"l2LivenessGuard": "SEQUENCER_OK"},
    {"sequencerAuthorityState": "SOURCE_PROVEN"},
    {"sequencerChecked": None},
])
def test_contradictory_recorded_liveness_context_fails_closed(store, override):
    raw_row(store, {**NO_SEQUENCER_EVIDENCE, **override})
    out = read_under(store, reg_not_published())
    assert out["state"] == "UNAVAILABLE" and out["reason"] == "ORACLE_SEQUENCER_EVIDENCE_POLICY_MISMATCH"


@pytest.mark.parametrize("override", [{"sequencerChecked": False}, {"sequencerGraceProtection": False},
                                       {"sequencerAnswer": 1}, {"sequencerFeed": None}])
def test_source_proven_row_with_incomplete_proof_fails_closed(store, override):
    payload = dict(collect(reg_source_proven()).evidence)
    payload.update(override)
    raw_row(store, payload)
    assert read_under(store, reg_source_proven())["reason"] == "ORACLE_SEQUENCER_EVIDENCE_POLICY_MISMATCH"


@pytest.mark.parametrize("persisted_state", ["STALE", "UNAVAILABLE"])
@pytest.mark.parametrize("current", [reg_not_published, reg_source_proven, reg_unreviewed])
def test_degrade_only_stale_or_unavailable_rows_never_become_available(store, persisted_state, current):
    payload = dict(NO_SEQUENCER_EVIDENCE) if current is not reg_source_proven else dict(collect(reg_source_proven()).evidence)
    raw_row(store, payload, state=persisted_state)
    out = read_under(store, current())
    assert out["state"] != "AVAILABLE" and out["persisted_state"] == persisted_state


def test_missing_source_timestamp_still_never_current_under_a_compatible_authority(store):
    raw_row(store, dict(NO_SEQUENCER_EVIDENCE), ts="")
    with sqlite3.connect(store.path) as conn:
        conn.execute("UPDATE source_evidence SET source_timestamp=NULL")
    assert read_under(store, reg_not_published())["reason"] == "ORACLE_SOURCE_TIMESTAMP_UNAVAILABLE"


def test_continuity_reads_write_nothing_and_do_not_infer_missing_fields(store):
    raw_row(store, {"heartbeatSeconds": 86400})
    before = dump(store)
    for current in (reg_not_published(), reg_source_proven(), reg_unreviewed()):
        read_under(store, current)
    assert dump(store) == before


def test_route_reports_the_continuity_result(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.radar_ui.r_live_router import router
    path = tmp_path / "evidence.db"
    SourceEvidenceStore(path).append(collect(reg_not_published()), collected_at=NOW)
    monkeypatch.setenv("FINCO_SOURCE_EVIDENCE_DB_PATH", str(path))
    app = FastAPI()
    app.include_router(router)
    body = TestClient(app).get(f"/radar/r-live/{NVDA_ID}/evidence").json()
    # shipped registry has no Stock Token binding, so the oracle leg is NOT REVIEWED regardless of the stored row
    assert body["legs"]["ORACLE"]["state"] == "UNAVAILABLE"
    assert body["legs"]["ORACLE"]["reason"] == "ORACLE_FEED_NOT_REVIEWED"
    assert body["legs"]["ORACLE"]["persisted_state"] == "AVAILABLE" and body["sequencer_authority"] == "OFFICIAL_FEED_NOT_PUBLISHED"


# ── authority-context digest + auditable dedupe ──────────────────────────────────────────────────
def test_a_later_poll_with_the_same_evidence_and_authority_context_dedupes(store):
    first = collect(reg_not_published(), first_block=1000)
    later = collect(reg_not_published(), first_block=1007, block_ts=BLOCK_TS + 7)     # a later collector poll
    assert first.digest() == later.digest()
    assert store.append(first, collected_at=NOW) is True
    assert store.append(later, collected_at=NOW + timedelta(minutes=5)) is False
    assert store.count() == 1


def test_authority_transition_with_identical_price_appends(store):
    fallback = collect(reg_not_published())
    proven = collect(reg_source_proven())
    assert (fallback.value, fallback.source_timestamp) == (proven.value, proven.source_timestamp)
    assert fallback.digest() != proven.digest()
    assert store.append(fallback, collected_at=NOW) and store.append(proven, collected_at=NOW + timedelta(minutes=5))
    assert store.count() == 2


def test_sequencer_proxy_change_under_source_proven_appends(store):
    a, b = collect(reg_source_proven(SEQ)), collect(reg_source_proven(SEQ2))
    assert (a.value, a.source_timestamp) == (b.value, b.source_timestamp) and a.digest() != b.digest()
    assert store.append(a, collected_at=NOW) and store.append(b, collected_at=NOW + timedelta(minutes=5))


def test_volatile_collection_block_metadata_never_creates_history(store):
    base = collect(reg_source_proven())
    other = collect(reg_source_proven(), first_block=5000, block_ts=BLOCK_TS + 9, round_id=8, answered_in=8)
    for volatile in ("blockNumber", "blockHash", "blockTimestamp"):
        assert base.evidence[volatile] != other.evidence[volatile]
    assert base.digest() == other.digest()
    assert store.append(base, collected_at=NOW) and not store.append(other, collected_at=NOW + timedelta(minutes=1))


@pytest.mark.parametrize("what,make", [
    ("heartbeat", lambda: collect(reg_not_published(heartbeat_seconds=3600))),
    ("binding review date", lambda: collect(OracleRegistry(
        {NVDA_ID: binding(provenance=Provenance(**{**PROV, "reviewed_at": "2026-11-01"}))}, None,
        SequencerAuthority("OFFICIAL_FEED_NOT_PUBLISHED", 4663, PROVENANCE)))),
])
def test_material_binding_changes_alter_the_context_digest(what, make):
    assert make().digest() != collect(reg_not_published()).digest(), what


def test_feed_proxy_change_alters_the_context_digest():
    leg = collect(reg_not_published())
    other = EvidenceLeg(leg.canonical_id, leg.role, leg.source_authority, leg.source_instrument, leg.state, leg.value,
                        leg.unit, leg.source_timestamp, leg.reason, {**leg.evidence, "feedProxy": "0x" + "e1" * 20})
    assert leg.digest() != other.digest()


def test_sequencer_status_change_after_recovery_alters_the_digest():
    before = collect(reg_source_proven())                                   # UP since BLOCK_TS - 86400
    after = collect(reg_source_proven(), extra=seq_extra(SEQ, started=BLOCK_TS - 7200))   # recovered 2h ago
    assert (before.value, before.source_timestamp) == (after.value, after.source_timestamp)
    assert before.digest() != after.digest()


def test_sequencer_grace_policy_change_alters_the_digest():
    assert collect(reg_source_proven(grace=3600)).digest() != collect(reg_source_proven(grace=1800)).digest()


def test_context_is_oracle_only_so_market_and_reference_digests_are_unchanged():
    def leg(role, evidence):
        return EvidenceLeg(NVDA_ID, role, "SRC", "inst", "AVAILABLE", Decimal("190"), "USD", NOW, None, evidence)
    for role in (EvidenceRole.MARKET, EvidenceRole.OFFICIAL_REFERENCE):
        assert leg(role, {"blockNumber": 1}).authority_context() is None
        assert leg(role, {"blockNumber": 1}).digest() == leg(role, {"blockNumber": 2, "x": "y"}).digest()


def test_unreviewed_oracle_legs_still_dedupe_cycle_after_cycle(store):
    leg = EvidenceLeg(NVDA_ID, EvidenceRole.ORACLE, "CHAINLINK_STOCK_TOKEN_PRICE_FEED", None, "UNAVAILABLE", None,
                      "USD_PER_STOCK_TOKEN", None, "ORACLE_FEED_NOT_REVIEWED", {})
    assert store.append(leg, collected_at=NOW) and not store.append(leg, collected_at=NOW + timedelta(minutes=5))


# ── unchanged commitments ────────────────────────────────────────────────────────────────────────
def test_fallback_evidence_still_never_claims_a_sequencer_check_or_ok_status():
    evidence = collect(reg_not_published()).evidence
    text = json.dumps(dict(evidence), default=str).upper()
    assert evidence["sequencerChecked"] is False and evidence["sequencerGraceProtection"] is False
    assert evidence["l2LivenessGuard"] == "PINNED_BLOCK_FRESHNESS_ONLY"
    assert "SEQUENCER_OK" not in text and "VERIFIED" not in text


def test_shipped_registry_authority_facts_are_unchanged():
    from app.radar_rwa.stock_token_oracle_registry import load_registry
    registry = load_registry()
    assert registry.sequencer is None and registry.sequencer_authority_state == "OFFICIAL_FEED_NOT_PUBLISHED"
    assert registry.sequencer_authority.provenance.reviewed_at == "2026-10-04"
    assert set(registry.coverage().values()) == {"ORACLE_FEED_NOT_REVIEWED"}
