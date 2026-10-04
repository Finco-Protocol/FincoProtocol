"""Exact identity resolution: one exact representation per reviewed R-LIVE deployment.

Instrument type is descriptive taxonomy, NOT identity-defining (RepresentationEntry.identity_key excludes it).
Sources that agree on every identity/safety fact collapse to one exact representation and keep their own
assertions; any identity-defining disagreement stays separate and fails closed.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from app.radar_rwa import tokenized_collect
from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID
from finco_radar.venues.models import CanonicalUnderlying, RegistryStatus, RepresentationEntry
from finco_radar.venues.registry import VenueRegistry
from finco_radar.venues.robinhood_live import (
    TokenizedLiveIdentityMismatch, _exact_robinhood_entry)

ADDR = "0x" + "a1" * 20
OTHER = "0x" + "b2" * 20


def row(source, *, itype="tokenized-equity", contract=ADDR, underlying="AAPL", symbol="AAPL",
        chain_id=4663, network="robinhood-chain", **kw):
    base = dict(
        platform="robinhood", representation_symbol=symbol, underlying_symbol=underlying,
        underlying_isin=None, isin=None, instrument_type=itype, name="Apple • Robinhood Token",
        network=network, chain_id=chain_id, contract_address=contract, decimals=18,
        deployment_status=None, trading_halted=None, deployments=(), source=source,
        source_ref=f"{source}@rev")
    base.update(kw)
    return RepresentationEntry(**base)


def reg(entries, quarantines=()):
    return VenueRegistry({"AAPL": CanonicalUnderlying("AAPL", None, None, ())}, list(entries), list(quarantines))


def lookup(registry, contract=ADDR):
    return registry.representation_by_contract(chain_id=4663, contract_address=contract)


# ── real seed: every reviewed identity ───────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def seed_registry():
    return VenueRegistry.load()


def test_reviewed_set_is_13():
    assert len(APPROVED_BY_CANONICAL_ID) == 13


def test_every_reviewed_identity_resolves_to_exactly_one_active_robinhood_representation(seed_registry):
    for canonical_id, policy in APPROVED_BY_CANONICAL_ID.items():
        chain, contract = canonical_id.split(":", 1)
        rows = lookup(seed_registry, contract) if chain == "4663" else \
            seed_registry.representation_by_contract(chain_id=int(chain), contract_address=contract)
        robinhood = [(e, s) for e, s in rows if e.platform == "robinhood"]
        assert len(robinhood) == 1, canonical_id
        entry, status = robinhood[0]
        assert status is RegistryStatus.ACTIVE
        assert entry.contract_address == contract.lower()
        assert entry.chain_id == int(chain)
        assert entry.underlying_symbol.upper() == policy.symbol
        assert not any(s in (RegistryStatus.QUARANTINED, RegistryStatus.CONFLICT) for _, s in rows)
        assert _exact_robinhood_entry(seed_registry, int(chain), contract.lower()) is entry


def test_collector_targets_equal_the_full_reviewed_set(seed_registry):
    targets = tokenized_collect._target_ids(seed_registry, max_assets=32)
    assert len(targets) == 13
    assert set(targets) == set(APPROVED_BY_CANONICAL_ID)


def test_reviewed_rows_keep_both_source_assertions(seed_registry):
    for canonical_id in APPROVED_BY_CANONICAL_ID:
        chain, contract = canonical_id.split(":", 1)
        entry = [e for e, _ in lookup(seed_registry, contract) if e.platform == "robinhood"][0]
        by_source = {a.source: a.instrument_type for a in entry.source_assertions}
        assert by_source == {"rwaimport-registry": "debt-security",
                             "xplowdie-rwa-registry": "tokenized-equity"}
        assert entry.instrument_type == "tokenized-equity"  # FINCO-recognised taxonomy value


def test_seed_collapse_counts_and_true_underlying_conflicts_remain(seed_registry):
    assert len(seed_registry._source_rows) == 2895
    assert len(seed_registry._entries) == 2717            # 178 same-identity pairs collapsed
    from app.radar_ui.tokenized_operational import _conflicted_contracts
    assert any(r == "UNDERLYING_CONFLICT_SAME_CONTRACT" for r in _conflicted_contracts(seed_registry).values())


def test_collapse_is_independent_of_input_order(seed_registry):
    rows = list(seed_registry._source_rows)
    reordered = VenueRegistry(seed_registry._underlyings, list(reversed(rows)), [])
    a = {e.identity_key: (e.instrument_type, e.source, e.source_assertions) for e in seed_registry._entries
         if e.source_assertions}
    b = {e.identity_key: (e.instrument_type, e.source, e.source_assertions) for e in reordered._entries
         if e.source_assertions}
    assert a == b and len(a) == 178


# ── synthetic fixtures ───────────────────────────────────────────────────────────────────────────
def test_two_sources_agreeing_on_identity_resolve_to_one_representation():
    registry = reg([row("src-a", itype="debt-security"), row("src-b", itype="tokenized-equity")])
    rows = lookup(registry)
    assert len(rows) == 1 and rows[0][1] is RegistryStatus.ACTIVE
    entry = rows[0][0]
    assert {a.source for a in entry.source_assertions} == {"src-a", "src-b"}
    assert _exact_robinhood_entry(registry, 4663, ADDR) is entry


def test_agreeing_sources_with_unrecognised_taxonomy_do_not_pick_a_winner():
    registry = reg([row("src-a", itype="debt-security"), row("src-b", itype="note")])
    entry = lookup(registry)[0][0]
    assert entry.instrument_type == "other"
    assert {a.instrument_type for a in entry.source_assertions} == {"debt-security", "note"}


def test_two_different_recognised_types_are_not_collapsed():
    registry = reg([row("src-a", itype="tokenized-equity"), row("src-b", itype="xstock")])
    assert len(lookup(registry)) == 2
    with pytest.raises(TokenizedLiveIdentityMismatch):
        _exact_robinhood_entry(registry, 4663, ADDR)


@pytest.mark.parametrize("override", [
    {"decimals": 6}, {"isin": "US0378331005"}, {"trading_halted": True},
    {"deployment_status": "inactive"}, {"name": "Different"}])
def test_any_identity_or_safety_fact_disagreement_is_not_collapsed(override):
    registry = reg([row("src-a", itype="debt-security"), row("src-b", **override)])
    assert len(lookup(registry)) == 2


def test_different_contracts_same_platform_symbol_network_conflict_closed():
    registry = reg([row("src-a", contract=ADDR), row("src-b", contract=OTHER)])
    for contract in (ADDR, OTHER):
        rows = lookup(registry, contract)
        assert rows and all(s is RegistryStatus.CONFLICT for _, s in rows)
        with pytest.raises(TokenizedLiveIdentityMismatch):
            _exact_robinhood_entry(registry, 4663, contract)


def test_same_contract_different_underlying_is_not_collapsed_and_fails_closed():
    registry = reg([row("src-a", underlying="AAPL"), row("src-b", underlying="MSFT")])
    assert len(lookup(registry)) == 2
    assert registry.underlying_for_contract(chain_id=4663, contract_address=ADDR) is None
    with pytest.raises(TokenizedLiveIdentityMismatch):
        _exact_robinhood_entry(registry, 4663, ADDR)


def test_quarantined_contract_never_becomes_active_even_when_sources_agree():
    quarantine = [{"network": "robinhood-chain", "chain_id": 4663, "contract_address": ADDR}]
    registry = reg([row("src-a", itype="debt-security"), row("src-b")], quarantine)
    rows = lookup(registry)
    assert rows and all(s is RegistryStatus.QUARANTINED for _, s in rows)
    with pytest.raises(TokenizedLiveIdentityMismatch):
        _exact_robinhood_entry(registry, 4663, ADDR)


def test_same_source_duplicate_is_not_treated_as_cross_source_agreement():
    registry = reg([row("src-a", itype="debt-security"), replace(row("src-a"), instrument_type="xstock")])
    assert len(lookup(registry)) == 2


def test_chain_id_disagreement_is_not_collapsed():
    registry = reg([row("src-a"), row("src-b", chain_id=None)])
    assert len(registry._entries) == 2
