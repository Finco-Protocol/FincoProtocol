"""Correction A additions for PR #182: populated-store binding, ACTIVE-only
dependencies, attestation PARTIAL aggregation, source-binding fail-closed."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.rwa_integrity.contracts import (
    EvidenceState,
    IdentityFlag,
    evaluate_attestations,
)
from app.rwa_integrity.read_model import build_underlying_integrity
from finco_radar.venues.models import RepresentationEntry
from finco_radar.venues.observations import (
    FreshnessState,
    MarketObservation,
    ObservationStatus,
)
from finco_radar.venues.registry import VenueRegistry, parse_underlying
from finco_radar.venues.store import VenueMarketStore

NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)
NVDA_CONTRACT = "0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec"


def _entry(**overrides) -> RepresentationEntry:
    base = dict(
        platform="robinhood", representation_symbol="NVDA",
        underlying_symbol="NVDA", underlying_isin="US67066G1040", isin=None,
        instrument_type="tokenized-equity", name="NVIDIA \u2022 Robinhood Token",
        network="robinhood-chain", chain_id=4663, contract_address=NVDA_CONTRACT,
        decimals=18, deployment_status="active", trading_halted=None,
        deployments=(), source="rwaimport-registry",
        source_ref="dicethedev/rwaimport-registry@a52ab34#assets/robinhood-nvda")
    base.update(overrides)
    return RepresentationEntry(**base)


def _underlying(**overrides):
    base = dict(canonical_symbol="NVDA", underlying_isin="US67066G1040",
                underlying_name="NVIDIA", sources=("test",))
    base.update(overrides)
    return parse_underlying(base)


def _registry(entries, quarantines=None) -> VenueRegistry:
    return VenueRegistry(
        {"NVDA": _underlying()}, list(entries), quarantines or [])


def _attestation(**overrides) -> dict:
    base = dict(
        canonical_asset_id="NVDA", chain_id=4663,
        contract_address=NVDA_CONTRACT,
        issuer_identity="robinhood-assets-jersey",
        custodian="test-custodian", attestation_provider="test-audit-firm",
        attestation_report_id="RPT-1",
        published_at=(NOW - timedelta(days=30)).isoformat(),
        source_uri="https://example.test/report.pdf",
        source_type="audit-firm", evidence_status="VERIFIED",
    )
    base.update(overrides)
    return base


def _observation_obj(store, *, price="196.00", ts=None, venue_id=None,
                     instrument_type=None, reference_price=None,
                     reference_state=None, reference_observed_at=None):
    observation = MarketObservation(
        ts=ts or (NOW - timedelta(seconds=60)).isoformat(),
        collected_at=(NOW - timedelta(seconds=55)).isoformat(),
        canonical_asset_id="NVDA",
        venue_id=venue_id or "robinhood-chain",
        instrument_id=NVDA_CONTRACT,
        instrument_type=instrument_type or "tokenized-equity",
        price=price,
        reference_price=reference_price,
        source="persisted-evidence",
        freshness_state=FreshnessState.AVAILABLE,
        observation_status=ObservationStatus.OK,
        payload={
            **({"reference_state": reference_state} if reference_state else {}),
            **({"reference_observed_at": reference_observed_at}
               if reference_observed_at else {}),
        },
    )
    store.append_observation(observation)


class TestPopulatedStoreBinding:
    def test_populated_store_produces_available(self):
        registry = _registry([_entry()])
        store = VenueMarketStore(_tmp_store())
        _observation_obj(store, price="196.00")
        view = build_underlying_integrity(
            "NVDA", registry=registry, store=store,
            attestations=[_attestation()], now=NOW)
        assert view.market_evidence_coverage == "AVAILABLE"
        rep = view.representations[0]
        assert rep.market_evidence_state == "AVAILABLE"
        assert rep.market_source_timestamp is not None

    def test_basis_propagates_from_179_authority(self):
        registry = _registry([_entry()])
        store = VenueMarketStore(_tmp_store())
        _observation_obj(store, price="196.00", reference_price="195.00",
                         reference_state="FRESH",
                         reference_observed_at=(NOW - timedelta(seconds=30)).isoformat())
        view = build_underlying_integrity(
            "NVDA", registry=registry, store=store,
            attestations=[_attestation()], now=NOW)
        rep = view.representations[0]
        assert rep.basis_evidence_state == "AVAILABLE"
        assert rep.basis_bps is not None
        # Must match #179 authority output, not independently recalculated.
        from finco_radar.venues.intelligence import build_tokenized_intelligence
        intel = build_tokenized_intelligence(
            "NVDA", registry=registry, store=store, as_of=NOW,
            include_points=False)
        assert rep.basis_bps == intel.representations[0].latest_basis_bps

    def test_exact_source_timestamp_propagated(self):
        registry = _registry([_entry()])
        store = VenueMarketStore(_tmp_store())
        exact_ts = "2026-10-01T10:00:00+00:00"
        _observation_obj(store, price="196.00", ts=exact_ts)
        view = build_underlying_integrity(
            "NVDA", registry=registry, store=store,
            attestations=[_attestation()], now=NOW)
        assert view.representations[0].market_source_timestamp == exact_ts

    def test_venue_collision_cannot_cross_bind(self):
        registry = _registry([_entry()])
        store = VenueMarketStore(_tmp_store())
        _observation_obj(store, price="999.00", venue_id="ethereum")
        view = build_underlying_integrity(
            "NVDA", registry=registry, store=store,
            attestations=[_attestation()], now=NOW)
        assert view.representations[0].market_evidence_state == "UNAVAILABLE"

    def test_representation_type_collision_cannot_cross_bind(self):
        registry = _registry([_entry()])
        store = VenueMarketStore(_tmp_store())
        _observation_obj(store, price="999.00", instrument_type="perpetual")
        view = build_underlying_integrity(
            "NVDA", registry=registry, store=store,
            attestations=[_attestation()], now=NOW)
        assert view.representations[0].market_evidence_state == "UNAVAILABLE"

    def test_single_venue_reference_available_cross_venue_unavailable(self):
        registry = _registry([_entry()])
        store = VenueMarketStore(_tmp_store())
        _observation_obj(store, price="196.00", reference_price="195.00",
                         reference_state="FRESH",
                         reference_observed_at=(NOW - timedelta(seconds=30)).isoformat())

        def reference_reader(symbol):
            return {"price": "195.00", "state": "FRESH"}

        view = build_underlying_integrity(
            "NVDA", registry=registry, store=store,
            attestations=[_attestation()], now=NOW,
            reference_evidence_reader=reference_reader)
        assert view.reference_evidence_state == "AVAILABLE"
        assert view.cross_venue_divergence_state == "UNAVAILABLE"


class TestDependencyFromActiveOnly:
    def test_quarantined_second_venue_keeps_dependencies(self):
        quarantined = _entry(
            platform="xstocks", representation_symbol="NVDAx",
            network="ethereum", chain_id=1,
            contract_address="0x" + "22" * 20,
            source="xstocks-official-api")
        registry = _registry([_entry(), quarantined], quarantines=[
            {"network": "ethereum", "contract_address": "0x" + "22" * 20,
             "classification": "impostor"}])
        view = build_underlying_integrity(
            "NVDA", registry=registry, store=None,
            attestations=[_attestation()], now=NOW)
        assert view.active_representation_count == 1
        assert IdentityFlag.SINGLE_VENUE_DEPENDENCY.value in view.dependency_flags
        assert IdentityFlag.SINGLE_REPRESENTATION_DEPENDENCY.value in (
            view.dependency_flags)
        assert view.quarantined_count == 1

    def test_conflicted_second_venue_does_not_remove_dependency(self):
        registry = _registry([
            _entry(source="source-a"),
            _entry(source="source-b", contract_address="0x" + "bb" * 20),
        ])
        view = build_underlying_integrity(
            "NVDA", registry=registry, store=None,
            attestations=[_attestation()], now=NOW)
        assert view.conflict_count >= 2
        assert IdentityFlag.SINGLE_VENUE_DEPENDENCY.value in view.dependency_flags


class TestAttestationCoverage:
    def _two_reps(self):
        second = _entry(
            platform="xstocks", representation_symbol="NVDAx",
            network="ethereum", chain_id=1,
            contract_address="0x" + "22" * 20,
            source="xstocks-official-api")
        return [_entry(), second]

    def test_all_active_verified(self):
        registry = _registry(self._two_reps())
        attestations = [
            _attestation(),
            _attestation(chain_id=1, contract_address="0x" + "22" * 20),
        ]
        view = build_underlying_integrity(
            "NVDA", registry=registry, store=None,
            attestations=attestations, now=NOW)
        assert view.attestation_evidence_state == "VERIFIED"

    def test_one_of_two_active_attested_is_partial(self):
        registry = _registry(self._two_reps())
        view = build_underlying_integrity(
            "NVDA", registry=registry, store=None,
            attestations=[_attestation()], now=NOW)
        assert view.attestation_evidence_state == "PARTIAL"

    def test_missing_source_uri_cannot_be_verified(self):
        evaluation = evaluate_attestations(
            [_attestation(source_uri="")],
            canonical_asset_id="NVDA", chain_id=4663,
            contract_address=NVDA_CONTRACT, now=NOW)
        assert evaluation.state is EvidenceState.UNAVAILABLE

    def test_source_type_unknown_cannot_be_verified(self):
        evaluation = evaluate_attestations(
            [_attestation(source_type="unknown")],
            canonical_asset_id="NVDA", chain_id=4663,
            contract_address=NVDA_CONTRACT, now=NOW)
        assert evaluation.state is EvidenceState.UNAVAILABLE

    def test_malformed_valid_through_fails_closed(self):
        evaluation = evaluate_attestations(
            [_attestation(valid_through="not-a-date")],
            canonical_asset_id="NVDA", chain_id=4663,
            contract_address=NVDA_CONTRACT, now=NOW)
        assert evaluation.state is EvidenceState.STALE
        assert evaluation.reason == "ATTESTATION_VALID_THROUGH_MALFORMED"

    def test_naive_valid_through_fails_closed(self):
        evaluation = evaluate_attestations(
            [_attestation(valid_through=(NOW + timedelta(days=90)).replace(
                tzinfo=None).isoformat())],
            canonical_asset_id="NVDA", chain_id=4663,
            contract_address=NVDA_CONTRACT, now=NOW)
        assert evaluation.state is EvidenceState.STALE

    def test_future_published_at_fails_closed(self):
        evaluation = evaluate_attestations(
            [_attestation(published_at=(NOW + timedelta(days=30)).isoformat())],
            canonical_asset_id="NVDA", chain_id=4663,
            contract_address=NVDA_CONTRACT, now=NOW)
        assert evaluation.state is EvidenceState.STALE
        assert evaluation.reason == "ATTESTATION_FUTURE_TIMESTAMP"

    def test_unknown_underlying_fails_closed(self):
        registry = _registry([_entry()])
        with pytest.raises(KeyError):
            build_underlying_integrity("ZZZZ", registry=registry, store=None,
                                       now=NOW)

    def test_market_authority_unavailable_degrades_only_market(self):
        view = build_underlying_integrity(
            "NVDA", registry=_registry([_entry()]), store=None,
            attestations=[_attestation()], now=NOW)
        assert view.market_evidence_coverage == "UNAVAILABLE"
        assert view.attestation_evidence_state == "VERIFIED"

    def test_attestation_authority_unavailable_degrades_only_attestation(self):
        registry = _registry([_entry()])
        store = VenueMarketStore(_tmp_store())
        _observation_obj(store, price="196.00")
        view = build_underlying_integrity(
            "NVDA", registry=registry, store=store,
            attestations=None, now=NOW)
        assert view.market_evidence_coverage == "AVAILABLE"
        assert view.attestation_evidence_state == "UNAVAILABLE"


def _tmp_store() -> str:
    import tempfile
    return str(Path(tempfile.mkdtemp()) / "venues.db")
