"""PR #188 Correction A: Source-legs gating, read-time EFFECTIVE status, single pinned oracle block.

Deterministic; no network. Persisted rows are immutable; presentation status is degrade-only and server-evaluated.
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.radar_rwa import multi_source_collect as msc
from app.radar_rwa.multi_source_evidence import (
    EvidenceLeg, EvidenceRole, SourceEvidenceStore, read_latest_legs_readonly,
)
from app.radar_rwa.r_live_service import R_LIVE_AUTHORITY_POLICY
from app.radar_rwa.stock_token_oracle import (
    NO_SEQUENCER_EVIDENCE, SEL_DECIMALS, SEL_DESCRIPTION, SEL_LATEST_ROUND, SEL_ORACLE_PAUSED, check_sequencer,
    pin_oracle_block, read_stock_token_oracle,
)
from app.radar_rwa.stock_token_oracle_registry import (
    OracleRegistry, Provenance, SequencerAuthority, load_registry,
)
from finco_radar.authority.contracts import AuthorityState
from finco_radar.authority.r_live_policy import (
    APPROVED_BY_CANONICAL_ID, MAX_BLOCK_AGE_SECONDS, MAX_QUOTE_AGE_SECONDS, TWAP_WINDOW_SECONDS,
)
from tests.test_multi_source_evidence_v2 import (
    AAPL_ID, AAPL_TOKEN, BLOCK_TS, FEED, NOW, NVDA_ID, NVDA_TOKEN, PROV, SEQ, FakeRpc, abi_string, binding, registry, word,
    _pair,
)

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)
HEARTBEAT = 3600
FEED2 = "0x" + "f2" * 20


def current_registry(**binding_kw) -> OracleRegistry:
    """The CURRENT reviewed registry used at read time: official sequencer absence reviewed, one reviewed feed binding."""
    binding_kw.setdefault("heartbeat_seconds", HEARTBEAT)
    return OracleRegistry({NVDA_ID: binding(**binding_kw)}, None,
                          SequencerAuthority("OFFICIAL_FEED_NOT_PUBLISHED", 4663, Provenance(**PROV)))


def leg(role, *, state="AVAILABLE", value="190", ts=T0, reason=None, evidence=None, cid=NVDA_ID):
    # An ORACLE observation always records the sequencer context it was collected under (here: official absence).
    base = dict(NO_SEQUENCER_EVIDENCE) if role is EvidenceRole.ORACLE else {}
    return EvidenceLeg(cid, role, f"SRC_{role.value}", "inst", state, None if value is None else Decimal(value),
                       "USD_PER_STOCK_TOKEN", ts, reason, {**base, **(evidence or {})})


def read_at(store, when, *, reg=None, cid=NVDA_ID):
    return read_latest_legs_readonly(
        cid, path=store.path, now=when,
        oracle_registry=reg if reg is not None else current_registry())["legs"]


@pytest.fixture()
def store(tmp_path):
    return SourceEvidenceStore(tmp_path / "evidence.db")


def dump(store) -> list[tuple]:
    with sqlite3.connect(store.path) as conn:
        return conn.execute("SELECT * FROM source_evidence ORDER BY seq").fetchall()


# ── 1. Source legs are independent of JEV visibility ─────────────────────────────────────────────
def _detail_client(monkeypatch, *, jev: bool):
    if jev:
        monkeypatch.setenv("FINCO_JEV_INTELLIGENCE_ENABLED", "1")
        monkeypatch.setenv("FINCO_JEV_INTELLIGENCE_MODE", "VISIBLE")
    else:
        monkeypatch.delenv("FINCO_JEV_INTELLIGENCE_ENABLED", raising=False)     # default state: JEV OFF
        monkeypatch.delenv("FINCO_JEV_INTELLIGENCE_MODE", raising=False)
    from app.radar_ui.r_live_router import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _scripts(html: str) -> list[str]:
    return re.findall(r"<script>(.*?)</script>", html, flags=re.S)


def test_source_legs_script_is_rendered_with_jev_off(monkeypatch):
    html = _detail_client(monkeypatch, jev=False).get(f"/radar/r-live/{NVDA_ID}").text
    assert 'data-testid="jev-intelligence-panel"' not in html            # JEV really is off on this page
    assert 'data-testid="source-legs"' in html
    scripts = [sc for sc in _scripts(html) if "EVIDENCE_URL" in sc]
    assert len(scripts) == 1 and f"/radar/r-live/" in scripts[0]
    assert "jev" not in scripts[0].lower()                               # not part of the JEV script


def test_source_legs_script_is_also_rendered_with_jev_on_and_jev_code_stays_separately_gated(monkeypatch):
    html = _detail_client(monkeypatch, jev=True).get(f"/radar/r-live/{NVDA_ID}").text
    assert 'data-testid="jev-intelligence-panel"' in html                # JEV really is visible on this page
    assert any("EVIDENCE_URL" in sc for sc in _scripts(html))
    assert not any("EVIDENCE_URL" in sc and "jev" in sc.lower() for sc in _scripts(html))


def test_source_legs_template_gate_is_row_approved_only():
    source = (ROOT / "app/templates/radar/r_live_detail.html").read_text(encoding="utf-8")
    index = source.index("var EVIDENCE_URL")
    gate = re.findall(r"\{% if ([^%]*?) %\}", source[:index])[-1]
    assert gate.strip() == "row.approved"
    assert "jev_visible" not in source[source.rindex("{% if row.approved %}", 0, index):index]


def test_unapproved_asset_renders_no_source_legs_script(monkeypatch):
    html = _detail_client(monkeypatch, jev=False).get("/radar/r-live/4663:0x" + "00" * 20).text
    assert "EVIDENCE_URL" not in html


NODE_HARNESS = r"""
const fs = require('fs');
const script = fs.readFileSync(process.argv[2], 'utf8');
const payload = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const rows = {};
['MARKET', 'OFFICIAL_REFERENCE', 'ORACLE'].forEach(r => {
  const cells = [0,1,2,3,4].map(() => ({ textContent: '', style: {} }));
  rows[r] = { cells, attrs: {}, querySelectorAll: () => cells, setAttribute(k, v) { this.attrs[k] = v; } };
});
const note = { textContent: 'loading' };
let fetched = null;
global.document = {
  querySelector: (sel) => { const m = sel.match(/data-leg='([A-Z_]+)'/); return m ? rows[m[1]] : null; },
  getElementById: (id) => id === 'source-legs-note' ? note : null,
};
global.fetch = (url) => { fetched = url; return Promise.resolve({ ok: payload !== null, json: () => Promise.resolve(payload) }); };
eval(script);
setTimeout(() => {
  const out = { fetched, note: note.textContent, rows: {} };
  Object.keys(rows).forEach(r => { out.rows[r] = rows[r].cells.map(c => c.textContent); out.rows[r].push(rows[r].attrs['data-effective-state'] || ''); });
  console.log(JSON.stringify(out));
}, 20);
"""


def _run_legs_script(tmp_path, monkeypatch, payload):
    if shutil.which("node") is None:
        pytest.skip("node unavailable")
    html = _detail_client(monkeypatch, jev=False).get(f"/radar/r-live/{NVDA_ID}").text
    script = next(sc for sc in _scripts(html) if "EVIDENCE_URL" in sc)
    (tmp_path / "script.js").write_text(script)
    (tmp_path / "payload.json").write_text(json.dumps(payload))
    (tmp_path / "harness.js").write_text(NODE_HARNESS)
    out = subprocess.run(["node", str(tmp_path / "harness.js"), str(tmp_path / "script.js"), str(tmp_path / "payload.json")],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_with_jev_off_the_source_legs_route_is_fetched_and_rendered(tmp_path, monkeypatch):
    payload = {"canonical_id": NVDA_ID, "oracle_binding": "ORACLE_FEED_NOT_REVIEWED", "legs": {
        "MARKET": {"state": "AVAILABLE", "persisted_state": "AVAILABLE", "value": "190.1", "age_seconds": 90,
                   "reason": None, "collected_at": "2026-10-05T12:00:00+00:00"},
        "OFFICIAL_REFERENCE": {"state": "STALE", "persisted_state": "AVAILABLE", "value": "189", "age_seconds": 90000,
                               "reason": "REFERENCE_STALE", "collected_at": "2026-10-04T12:00:00+00:00"},
        "ORACLE": None}}
    result = _run_legs_script(tmp_path, monkeypatch, payload)
    assert result["fetched"] == f"/radar/r-live/{NVDA_ID.replace(':', '%3A')}/evidence"
    market, reference, oracle = (result["rows"][k] for k in ("MARKET", "OFFICIAL_REFERENCE", "ORACLE"))
    assert market[1] == "AVAILABLE" and market[2] == "$190.1000" and market[3] == "1m"
    assert reference[1] == "STALE" and reference[2] == "—"          # numbers only while effective status is AVAILABLE
    assert result["note"] == ""


def test_zero_binding_presentation_is_clear_not_loading_and_has_no_fake_zero(tmp_path, monkeypatch):
    payload = {"canonical_id": NVDA_ID, "oracle_binding": "ORACLE_FEED_NOT_REVIEWED",
               "legs": {"MARKET": None, "OFFICIAL_REFERENCE": None, "ORACLE": None}}
    result = _run_legs_script(tmp_path, monkeypatch, payload)
    oracle = result["rows"]["ORACLE"]
    assert oracle[1] == "NOT REVIEWED" and oracle[2] == "—" and "$0" not in " ".join(oracle)
    assert "…" not in " ".join(oracle) and "loading" not in " ".join(oracle).lower()
    assert result["rows"]["MARKET"][1] == "NOT COLLECTED"            # independent of the oracle


def test_zero_binding_oracle_leg_with_a_persisted_row_reads_not_reviewed(tmp_path, monkeypatch):
    payload = {"canonical_id": NVDA_ID, "oracle_binding": "ORACLE_FEED_NOT_REVIEWED", "legs": {
        "MARKET": None, "OFFICIAL_REFERENCE": None,
        "ORACLE": {"state": "UNAVAILABLE", "persisted_state": "AVAILABLE", "value": "190", "age_seconds": 5,
                   "reason": "ORACLE_FEED_NOT_REVIEWED", "collected_at": "2026-10-05T12:00:00+00:00"}}}
    oracle = _run_legs_script(tmp_path, monkeypatch, payload)["rows"]["ORACLE"]
    assert oracle[1] == "NOT REVIEWED" and oracle[2] == "—"


def test_unreachable_route_resolves_to_unavailable_not_a_permanent_placeholder(tmp_path, monkeypatch):
    result = _run_legs_script(tmp_path, monkeypatch, None)
    assert all(result["rows"][k][1] == "UNAVAILABLE" for k in result["rows"]) and result["note"] != "loading"


# ── 2. Read-time ORACLE aging ────────────────────────────────────────────────────────────────────
def test_oracle_aging_available_at_heartbeat_stale_one_second_after_and_row_unchanged(store):
    store.append(leg(EvidenceRole.ORACLE), collected_at=T0)
    before = dump(store)
    at_edge = read_at(store, T0 + timedelta(seconds=HEARTBEAT))["ORACLE"]
    assert at_edge["state"] == "AVAILABLE" and at_edge["reason"] is None
    late = read_at(store, T0 + timedelta(seconds=HEARTBEAT + 1))["ORACLE"]
    assert late["state"] == "STALE" and late["reason"] == "ORACLE_HEARTBEAT_EXCEEDED"
    assert late["persisted_state"] == "AVAILABLE" and late["heartbeat_seconds"] == HEARTBEAT
    assert dump(store) == before                                     # immutable: no writes occurred


def test_oracle_heartbeat_comes_from_the_current_registry_not_the_persisted_payload(store):
    store.append(leg(EvidenceRole.ORACLE, evidence={"heartbeatSeconds": 10**9}), collected_at=T0)
    short = current_registry(heartbeat_seconds=60)
    assert read_at(store, T0 + timedelta(seconds=120), reg=short)["ORACLE"]["state"] == "STALE"
    long_ = current_registry(heartbeat_seconds=86400)
    assert read_at(store, T0 + timedelta(seconds=120), reg=long_)["ORACLE"]["state"] == "AVAILABLE"


def test_oracle_without_a_current_reviewed_binding_is_unavailable_even_if_persisted_available(store):
    store.append(leg(EvidenceRole.ORACLE), collected_at=T0)
    oracle = read_at(store, T0 + timedelta(seconds=1), reg=OracleRegistry({}, None))["ORACLE"]
    assert oracle["state"] == "UNAVAILABLE" and oracle["reason"] == "ORACLE_FEED_NOT_REVIEWED"
    assert oracle["persisted_state"] == "AVAILABLE" and oracle["heartbeat_seconds"] is None


def test_shipped_zero_binding_registry_makes_every_persisted_oracle_row_not_reviewed(store):
    store.append(leg(EvidenceRole.ORACLE), collected_at=T0)
    legs = read_latest_legs_readonly(NVDA_ID, path=store.path, now=T0, oracle_registry=load_registry())["legs"]
    assert legs["ORACLE"]["state"] == "UNAVAILABLE" and legs["ORACLE"]["reason"] == "ORACLE_FEED_NOT_REVIEWED"


def test_oracle_binding_without_a_reviewed_heartbeat_is_unavailable(store):
    store.append(leg(EvidenceRole.ORACLE), collected_at=T0)
    oracle = read_at(store, T0, reg=current_registry(heartbeat_seconds=None))["ORACLE"]
    assert oracle["state"] == "UNAVAILABLE" and oracle["reason"] == "ORACLE_HEARTBEAT_NOT_REVIEWED"


def _insert_raw(store, role, state, *, ts, payload="{}", reason=None, value="190"):
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "INSERT INTO source_evidence (digest, canonical_id, canonical_asset_id, evidence_role, source_authority, "
            "source_instrument, value, unit, source_timestamp, collected_at, state, reason, payload) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"d-{role}-{state}-{ts}", NVDA_ID, "NVDA", role, "SRC", "inst", value, "USD", ts, T0.isoformat(), state,
             reason, payload))


def test_available_oracle_row_without_a_source_timestamp_never_becomes_current(store):
    _insert_raw(store, "ORACLE", "AVAILABLE", ts=None, payload=json.dumps(dict(NO_SEQUENCER_EVIDENCE)))
    oracle = read_at(store, T0)["ORACLE"]
    assert oracle["state"] == "UNAVAILABLE" and oracle["reason"] == "ORACLE_SOURCE_TIMESTAMP_UNAVAILABLE"


@pytest.mark.parametrize("persisted", ["STALE", "UNAVAILABLE"])
@pytest.mark.parametrize("role", list(EvidenceRole))
def test_stale_or_unavailable_rows_are_never_promoted_to_available_on_read(store, role, persisted):
    payload = json.dumps({"blockTimestamp": T0.isoformat(), "lastPoolActivityAt": T0.isoformat(),
                          "quoteUpdatedAt": T0.isoformat()})
    _insert_raw(store, role.value, persisted, ts=T0.isoformat(), payload=payload, reason="PERSISTED_REASON")
    out = read_at(store, T0)[role.value]                              # perfectly fresh evidence at read time
    assert out["state"] != "AVAILABLE" and out["persisted_state"] == persisted


@pytest.mark.parametrize("role", list(EvidenceRole))
def test_available_row_with_missing_source_timestamp_never_reads_current(store, role):
    _insert_raw(store, role.value, "AVAILABLE", ts=None)
    assert read_at(store, T0)[role.value]["state"] != "AVAILABLE"


# ── 3. Read-time OFFICIAL_REFERENCE aging (existing R-LIVE authority policy) ─────────────────────
REFERENCE_MAX = R_LIVE_AUTHORITY_POLICY.max_reference_age_seconds


def test_reference_uses_the_existing_authority_policy_value():
    assert REFERENCE_MAX == MAX_QUOTE_AGE_SECONDS == 86400


def test_reference_aging_follows_the_existing_authority_age_test_and_row_is_unchanged(store):
    store.append(leg(EvidenceRole.OFFICIAL_REFERENCE), collected_at=T0)
    before = dump(store)
    assert read_at(store, T0 + timedelta(seconds=REFERENCE_MAX))["OFFICIAL_REFERENCE"]["state"] == "AVAILABLE"
    late = read_at(store, T0 + timedelta(seconds=REFERENCE_MAX + 1))["OFFICIAL_REFERENCE"]
    assert late["state"] == "STALE" and late["reason"] == "REFERENCE_STALE" and late["persisted_state"] == "AVAILABLE"
    assert dump(store) == before


def test_reference_future_dated_evidence_is_not_current(store):
    store.append(leg(EvidenceRole.OFFICIAL_REFERENCE, ts=T0 + timedelta(hours=1)), collected_at=T0)
    assert read_at(store, T0)["OFFICIAL_REFERENCE"]["state"] == "STALE"


def test_reference_missing_timestamp_fails_closed(store):
    _insert_raw(store, "OFFICIAL_REFERENCE", "AVAILABLE", ts=None)
    ref = read_at(store, T0)["OFFICIAL_REFERENCE"]
    assert ref["state"] == "UNAVAILABLE" and ref["reason"] == "REFERENCE_SOURCE_TIMESTAMP_UNAVAILABLE"


# ── 4. Read-time MARKET aging (existing R-LIVE snapshot re-evaluation contract) ──────────────────
def market_evidence(*, block=T0, pool=T0 - timedelta(seconds=10), quote=T0 - timedelta(hours=1)):
    return {"blockTimestamp": block.isoformat(), "lastPoolActivityAt": pool.isoformat(),
            "quoteUpdatedAt": quote.isoformat()}


def test_market_reuses_the_existing_snapshot_limits():
    assert MAX_BLOCK_AGE_SECONDS == 120 and TWAP_WINDOW_SECONDS == 300 and MAX_QUOTE_AGE_SECONDS == 86400


def test_market_block_leg_aging_and_row_unchanged(store):
    store.append(leg(EvidenceRole.MARKET, evidence=market_evidence()), collected_at=T0)
    before = dump(store)
    assert read_at(store, T0 + timedelta(seconds=MAX_BLOCK_AGE_SECONDS))["MARKET"]["state"] == "AVAILABLE"
    late = read_at(store, T0 + timedelta(seconds=MAX_BLOCK_AGE_SECONDS + 1))["MARKET"]
    assert late["state"] == "STALE" and late["reason"] == "SNAPSHOT_EVIDENCE_BLOCK_EXPIRED"
    assert late["persisted_state"] == "AVAILABLE"
    assert dump(store) == before


def test_market_pool_activity_leg_aging(store):
    store.append(leg(EvidenceRole.MARKET, evidence=market_evidence(pool=T0 - timedelta(seconds=TWAP_WINDOW_SECONDS - 5))),
                 collected_at=T0)
    assert read_at(store, T0 + timedelta(seconds=5))["MARKET"]["state"] == "AVAILABLE"
    late = read_at(store, T0 + timedelta(seconds=6))["MARKET"]
    assert late["state"] == "STALE" and late["reason"] == "SNAPSHOT_EVIDENCE_POOL_ACTIVITY_EXPIRED"


def test_market_quote_leg_aging(store):
    store.append(leg(EvidenceRole.MARKET, evidence=market_evidence(quote=T0 - timedelta(seconds=MAX_QUOTE_AGE_SECONDS - 5))),
                 collected_at=T0)
    assert read_at(store, T0 + timedelta(seconds=5))["MARKET"]["state"] == "AVAILABLE"
    late = read_at(store, T0 + timedelta(seconds=6))["MARKET"]
    assert late["state"] == "STALE" and late["reason"] == "SNAPSHOT_EVIDENCE_QUOTE_EXPIRED"


def test_market_incomplete_evidence_is_unavailable_never_current(store):
    store.append(leg(EvidenceRole.MARKET, evidence={"lastPoolActivityAt": T0.isoformat()}), collected_at=T0)
    market = read_at(store, T0)["MARKET"]
    assert market["state"] == "UNAVAILABLE" and market["reason"] == "SNAPSHOT_EVIDENCE_INCOMPLETE"


def test_market_never_uses_collected_at_as_evidence_time(store):
    # evidence is old; collected_at is "now". Status must follow the evidence, not the collector clock.
    old = market_evidence(block=T0 - timedelta(hours=2), pool=T0 - timedelta(hours=2))
    store.append(leg(EvidenceRole.MARKET, ts=T0 - timedelta(hours=2), evidence=old), collected_at=T0)
    assert read_at(store, T0)["MARKET"]["state"] == "STALE"


def test_a_fresh_oracle_or_reference_never_makes_a_stale_market_current_on_read(store):
    stale_market = market_evidence(block=T0 - timedelta(hours=1), pool=T0 - timedelta(hours=1))
    store.append(leg(EvidenceRole.MARKET, evidence=stale_market), collected_at=T0)
    store.append(leg(EvidenceRole.OFFICIAL_REFERENCE), collected_at=T0)
    store.append(leg(EvidenceRole.ORACLE), collected_at=T0)
    legs = read_at(store, T0)
    assert legs["MARKET"]["state"] == "STALE"
    assert legs["OFFICIAL_REFERENCE"]["state"] == legs["ORACLE"]["state"] == "AVAILABLE"


# ── 5. Read path stays write-free, provider-free, exact-identity ─────────────────────────────────
def test_read_path_is_write_free_and_network_free(store, monkeypatch):
    import socket
    import httpx
    store.append(leg(EvidenceRole.ORACLE), collected_at=T0)
    before = dump(store)
    monkeypatch.setattr(httpx.Client, "send", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    for offset in (0, HEARTBEAT + 1, 10**6):
        read_at(store, T0 + timedelta(seconds=offset))
    assert dump(store) == before


def test_route_reports_effective_status_with_persisted_status_and_never_writes(tmp_path, monkeypatch):
    from app.radar_ui.r_live_router import router
    path = tmp_path / "evidence.db"
    SourceEvidenceStore(path).append(leg(EvidenceRole.OFFICIAL_REFERENCE, ts=datetime.now(timezone.utc) - timedelta(days=3)),
                                     collected_at=T0)
    monkeypatch.setenv("FINCO_SOURCE_EVIDENCE_DB_PATH", str(path))
    app = FastAPI()
    app.include_router(router)
    before = dump(SourceEvidenceStore(path))
    body = TestClient(app).get(f"/radar/r-live/{NVDA_ID}/evidence").json()
    ref = body["legs"]["OFFICIAL_REFERENCE"]
    assert ref["state"] == "STALE" and ref["persisted_state"] == "AVAILABLE" and ref["reason"] == "REFERENCE_STALE"
    assert set(ref) >= {"state", "persisted_state", "value", "source_timestamp", "collected_at", "age_seconds", "reason",
                        "source_authority", "source_instrument", "heartbeat_seconds"}
    assert body["oracle_binding"] == "ORACLE_FEED_NOT_REVIEWED" and body["legs"]["ORACLE"] is None
    assert dump(SourceEvidenceStore(path)) == before


# ── 6. ONE pinned oracle block ───────────────────────────────────────────────────────────────────
def test_one_oracle_observation_pins_n_once_and_uses_tag_n_everywhere():
    rpc = FakeRpc(advance=True)                    # a SECOND ``latest`` read would return N+1
    obs = read_stock_token_oracle(rpc=rpc, registry=registry(), canonical_id=NVDA_ID, as_of=NOW)
    assert obs.state is AuthorityState.AVAILABLE
    assert rpc.latest_calls == 1 and rpc.block_reads == ["latest", "0x3e8"]       # pin once, verify by exact tag
    assert rpc.tags == ["0x3e8"] * len(rpc.tags) and len(rpc.tags) == 5
    seen = {(to, data): tag for (to, data), tag in zip(rpc.calls, rpc.tags)}
    for key in ((SEQ, SEL_LATEST_ROUND), (NVDA_TOKEN, SEL_ORACLE_PAUSED), (FEED, SEL_DESCRIPTION), (FEED, SEL_DECIMALS),
                (FEED, SEL_LATEST_ROUND)):
        assert seen[key] == "0x3e8", key
    assert obs.evidence["blockNumber"] == 1000


def _two_asset_rpc(**kw) -> FakeRpc:
    extra = {
        (FEED2, SEL_DESCRIPTION): abi_string("AAPL / USD"),
        (FEED2, SEL_DECIMALS): "0x" + word(8),
        (FEED2, SEL_LATEST_ROUND): "0x" + word(9) + word(200_00000000) + word(BLOCK_TS - 70) + word(BLOCK_TS - 60) + word(9),
        (AAPL_TOKEN, SEL_ORACLE_PAUSED): "0x" + word(0),
    }
    return FakeRpc(extra=extra, **kw)


def _two_asset_registry() -> OracleRegistry:
    aapl = binding(canonical_id=AAPL_ID, token_contract=AAPL_TOKEN, feed_proxy=FEED2, feed_description="AAPL / USD")
    return registry(bindings=[binding(), aapl])


def test_multi_asset_cycle_uses_the_same_pinned_block_for_every_bound_asset():
    rpc = _two_asset_rpc(advance=True)
    report = msc.collect_multi_source_once(acquire_asset=_pair, oracle_rpc=rpc, oracle_registry=_two_asset_registry(),
                                           as_of=NOW, workers=2)
    rows = {r["symbol"]: r["ORACLE"] for r in report["matrix"]}
    assert rows["NVDA"]["state"] == rows["AAPL"]["state"] == "AVAILABLE"
    assert rpc.latest_calls == 1                                   # the cycle pinned ONE block
    assert set(rpc.tags) == {"0x3e8"} and len(rpc.tags) == 1 + 2 * 4   # sequencer once + 4 reads per asset
    assert [r for r in rpc.block_reads if r == "latest"] == ["latest"]
    assert set(r for r in rpc.block_reads if r != "latest") == {"0x3e8"}   # every final hash validation checks N


def test_a_sequencer_reading_from_a_different_block_is_rejected():
    rpc = FakeRpc()
    other = pin_oracle_block(FakeRpc(first_block=2000), as_of=NOW)
    foreign = check_sequencer(rpc, registry().sequencer, other)
    obs = read_stock_token_oracle(rpc=rpc, registry=registry(), canonical_id=NVDA_ID, as_of=NOW, sequencer=foreign)
    assert obs.state is AuthorityState.UNAVAILABLE and obs.reason == "ORACLE_SEQUENCER_BLOCK_MISMATCH"


def test_reorg_of_the_pinned_block_makes_the_observation_unavailable():
    obs = read_stock_token_oracle(rpc=FakeRpc(reorg=True), registry=registry(), canonical_id=NVDA_ID, as_of=NOW)
    assert obs.state is AuthorityState.UNAVAILABLE and obs.reason == "ORACLE_BLOCK_REORG_OR_MISMATCH" and obs.value is None


def test_reorg_in_a_cycle_leaves_no_available_oracle_leg_but_keeps_market_and_reference():
    report = msc.collect_multi_source_once(acquire_asset=_pair, oracle_rpc=_two_asset_rpc(reorg=True),
                                           oracle_registry=_two_asset_registry(), as_of=NOW)
    for symbol in ("NVDA", "AAPL"):
        row = next(r for r in report["matrix"] if r["symbol"] == symbol)
        assert row["ORACLE"]["state"] == "UNAVAILABLE" and row["ORACLE"]["reason"] == "ORACLE_BLOCK_REORG_OR_MISMATCH"
        assert row["MARKET"]["state"] == row["OFFICIAL_REFERENCE"]["state"] == "AVAILABLE"


def test_cycle_level_block_failures_are_typed_for_every_bound_asset():
    stale = msc.collect_multi_source_once(acquire_asset=_pair, oracle_rpc=_two_asset_rpc(block_ts=int(NOW.timestamp()) - 3600),
                                          oracle_registry=_two_asset_registry(), as_of=NOW)
    down = msc.collect_multi_source_once(acquire_asset=_pair, oracle_rpc=_two_asset_rpc(fail={"block"}),
                                         oracle_registry=_two_asset_registry(), as_of=NOW)
    for report, reason in ((stale, "ORACLE_CHAIN_BLOCK_STALE"), (down, "ORACLE_RPC_UNAVAILABLE")):
        for symbol in ("NVDA", "AAPL"):
            assert next(r for r in report["matrix"] if r["symbol"] == symbol)["ORACLE"]["reason"] == reason


def test_unbound_assets_never_trigger_a_block_read():
    rpc = FakeRpc()
    msc.collect_multi_source_once(acquire_asset=_pair, oracle_rpc=rpc, oracle_registry=OracleRegistry({}, None), as_of=NOW)
    assert rpc.block_reads == [] and rpc.calls == []


def test_registry_still_has_zero_source_proven_bindings():
    coverage = load_registry().coverage()
    assert len(coverage) == 13 and set(coverage.values()) == {"ORACLE_FEED_NOT_REVIEWED"}
