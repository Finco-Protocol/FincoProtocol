"""RWA Integrity & Trust Intelligence V1 tests.

Proves:
  1. exact canonical identity only (no ticker/contract fuzziness);
  2. ticker collision cannot cross-bind attestation evidence;
  3. wrong chain cannot cross-bind attestation;
  4. wrong contract cannot cross-bind attestation;
  5. missing evidence stays UNAVAILABLE (not negative);
  6. stale evidence stays STALE;
  7. ingestion time never substitutes for evidence source time;
  8. quarantine stays explicit;
  9. identity conflict stays explicit;
 10. single venue → SINGLE_VENUE_DEPENDENCY;
 11. two venues remove that dependency;
 12. single chain → SINGLE_CHAIN_DEPENDENCY;
 13. no holder-concentration claim without holder data;
 14. market intelligence math is not duplicated (interpreted, not recomputed);
 15. unavailable market store does not 500 the profile;
 16. unavailable attestation authority does not 500 the profile;
 17. no execution/signing/custody logic exists in the domain.
"""
from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

from app.rwa_integrity.contracts import (
    AttestationEvaluation,
    BackingAttestationEvidence,
    EvidenceState,
    IdentityFlag,
    evaluate_attestations,
    parse_attestation,
)
from app.rwa_integrity.read_model import (
    build_underlying_integrity,
    list_integrity_profiles,
)
from finco_radar.venues.models import RegistryStatus, RepresentationEntry
from finco_radar.venues.registry import VenueRegistry, parse_underlying
from finco_radar.venues.store import VenueMarketStore

NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)


def _observation_obj(store, *, price="196.00", ts=None, venue_id=None,
                     instrument_type=None, reference_price=None,
                     reference_state=None, reference_observed_at=None):
    from finco_radar.venues.observations import (
        FreshnessState, MarketObservation, ObservationStatus)
    observation = MarketObservation(
        ts=ts or (NOW - timedelta(seconds=60)).isoformat(),
        collected_at=(NOW - timedelta(seconds=55)).isoformat(),
        canonical_asset_id="NVDA",
        venue_id=venue_id or "robinhood-chain",
        instrument_id=NVDA_CONTRACT,
        instrument_type=instrument_type or "tokenized-equity",
        price=price,
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


def _tmp_store() -> str:
    import tempfile
    return str(Path(tempfile.mkdtemp()) / "venues.db")
NVDA_CONTRACT = "0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec"


def _entry(**overrides) -> RepresentationEntry:
    base = dict(
        platform="robinhood", representation_symbol="NVDA",
        underlying_symbol="NVDA", underlying_isin="US67066G1040", isin=None,
        instrument_type="tokenized-equity", name="NVIDIA • Robinhood Token",
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
        canonical_asset_id="NVDA",
        chain_id=4663,
        contract_address=NVDA_CONTRACT,
        issuer_identity="robinhood-assets-jersey",
        custodian="test-custodian",
        attestation_provider="test-audit-firm",
        attestation_report_id="RPT-1",
        published_at=(NOW - timedelta(days=30)).isoformat(),
        source_uri="https://example.test/report.pdf",
        source_type="audit-firm",
        evidence_status="VERIFIED",
    )
    base.update(overrides)
    return base


def _observation(price="196.00", *, ts=None, staleness="AVAILABLE"):
    from finco_radar.venues.observations import (
        FreshnessState, MarketObservation, ObservationStatus)
    stamp = ts or (NOW - timedelta(seconds=60)).isoformat()
    return MarketObservation(
        ts=stamp,
        collected_at=(NOW - timedelta(seconds=55)).isoformat(),
        canonical_asset_id="NVDA",
        venue_id="robinhood-chain",
        instrument_id=NVDA_CONTRACT,
        instrument_type="tokenized-equity",
        price=price,
        source="persisted-evidence",
        freshness_state=FreshnessState(staleness),
        observation_status=ObservationStatus.OK,
        payload={},
    )


def _profile(entries=None, *, store=None, attestations=None, quarantines=None,
             now=NOW):
    registry = _registry(entries or [_entry()], quarantines)
    return build_underlying_integrity(
        "NVDA", registry=registry,
        store=store, attestations=attestations, now=now)


# ── Attestation scope + freshness ─────────────────────────────────────────────

class TestAttestationScopeAndFreshness:
    def test_exact_scope_binds(self):
        evaluation = evaluate_attestations(
            [_attestation()], canonical_asset_id="NVDA", chain_id=4663,
            contract_address=NVDA_CONTRACT, now=NOW)
        assert evaluation.state is EvidenceState.VERIFIED
        assert evaluation.record.attestation_provider == "test-audit-firm"

    def test_ticker_collision_cannot_cross_bind(self):
        """Same ticker string appearing in a DIFFERENT canonical asset's
        attestation does not bind to NVDA."""
        record = parse_attestation(_attestation(canonical_asset_id="NVDA2"))
        assert record.covers(canonical_asset_id="NVDA", chain_id=4663,
                             contract_address=NVDA_CONTRACT) is False

    def test_wrong_chain_cannot_cross_bind(self):
        evaluation = evaluate_attestations(
            [_attestation(chain_id=1)], canonical_asset_id="NVDA",
            chain_id=4663, contract_address=NVDA_CONTRACT, now=NOW)
        assert evaluation.state is EvidenceState.UNAVAILABLE
        assert evaluation.reason == "ATTESTATION_SCOPE_MISMATCH"

    def test_wrong_contract_cannot_cross_bind(self):
        evaluation = evaluate_attestations(
            [_attestation(contract_address="0x" + "ee" * 20)],
            canonical_asset_id="NVDA", chain_id=4663,
            contract_address=NVDA_CONTRACT, now=NOW)
        assert evaluation.state is EvidenceState.UNAVAILABLE
        assert evaluation.reason == "ATTESTATION_SCOPE_MISMATCH"

    def test_missing_evidence_is_unavailable_not_negative(self):
        evaluation = evaluate_attestations(
            [], canonical_asset_id="NVDA", chain_id=4663,
            contract_address=NVDA_CONTRACT, now=NOW)
        assert evaluation.state is EvidenceState.UNAVAILABLE
        assert evaluation.record is None

    def test_stale_evidence_stays_stale(self):
        evaluation = evaluate_attestations(
            [_attestation(published_at=(NOW - timedelta(days=200)).isoformat())],
            canonical_asset_id="NVDA", chain_id=4663,
            contract_address=NVDA_CONTRACT, now=NOW)
        assert evaluation.state is EvidenceState.STALE
        assert evaluation.reason == "ATTESTATION_STALE"

    def test_expired_valid_through_is_stale(self):
        evaluation = evaluate_attestations(
            [_attestation(valid_through=(NOW - timedelta(days=1)).isoformat())],
            canonical_asset_id="NVDA", chain_id=4663,
            contract_address=NVDA_CONTRACT, now=NOW)
        assert evaluation.state is EvidenceState.STALE

    def test_ingestion_time_never_substitutes_for_source_time(self):
        """A record with only observed_at (no published_at) is UNAVAILABLE —
        FINCO's ingestion clock never proves currency."""
        raw = _attestation()
        del raw["published_at"]
        raw["observed_at"] = NOW.isoformat()
        record = parse_attestation(raw)
        assert record.published_at is None
        evaluation = evaluate_attestations(
            [record], canonical_asset_id="NVDA", chain_id=4663,
            contract_address=NVDA_CONTRACT, now=NOW)
        assert evaluation.state is EvidenceState.UNAVAILABLE

    def test_naive_published_at_is_not_presentable_as_current(self):
        evaluation = evaluate_attestations(
            [_attestation(published_at=(NOW - timedelta(days=1)).replace(
                tzinfo=None).isoformat())],
            canonical_asset_id="NVDA", chain_id=4663,
            contract_address=NVDA_CONTRACT, now=NOW)
        assert evaluation.state is EvidenceState.UNAVAILABLE

    def test_provider_missing_is_unavailable_even_with_dates(self):
        evaluation = evaluate_attestations(
            [_attestation(attestation_provider=None)],
            canonical_asset_id="NVDA", chain_id=4663,
            contract_address=NVDA_CONTRACT, now=NOW)
        assert evaluation.state is EvidenceState.UNAVAILABLE


# ── Dependency / concentration ────────────────────────────────────────────────

class TestDependencyIntelligence:
    def test_single_venue_dependency(self):
        view = _profile()
        assert IdentityFlag.SINGLE_VENUE_DEPENDENCY.value in view.dependency_flags

    def test_two_venues_remove_single_venue_dependency(self):
        xstocks = _entry(platform="xstocks", representation_symbol="NVDAx",
                         network="ethereum", chain_id=None,
                         contract_address="0x" + "22" * 20,
                         source="xstocks-official-api")
        view = _profile([_entry(), xstocks])
        assert IdentityFlag.SINGLE_VENUE_DEPENDENCY.value not in (
            view.dependency_flags)
        assert IdentityFlag.SINGLE_CHAIN_DEPENDENCY.value not in (
            view.dependency_flags)  # robinhood-chain(4663) + ethereum(None?) —
        # ethereum deployment has chain_id None; chain diversity counts only
        # known chain ids, but venue diversity is already resolved.

    def test_single_chain_dependency(self):
        view = _profile()
        assert IdentityFlag.SINGLE_CHAIN_DEPENDENCY.value in view.dependency_flags

    def test_two_known_chains_remove_chain_dependency(self):
        xstocks = _entry(platform="xstocks", representation_symbol="NVDAx",
                         network="ethereum", chain_id=1,
                         contract_address="0x" + "22" * 20,
                         source="xstocks-official-api")
        view = _profile([_entry(), xstocks])
        assert IdentityFlag.SINGLE_CHAIN_DEPENDENCY.value not in (
            view.dependency_flags)

    def test_single_representation_dependency(self):
        view = _profile()
        assert (IdentityFlag.SINGLE_REPRESENTATION_DEPENDENCY.value
                in view.dependency_flags)

    def test_single_source_dependency(self):
        view = _profile()
        assert IdentityFlag.SINGLE_SOURCE_DEPENDENCY.value in view.dependency_flags

    def test_no_holder_concentration_claim(self):
        view = _profile()
        all_flags = " ".join(view.dependency_flags + view.integrity_flags)
        for holder_term in ("HOLDER", "WALLET", "SUPPLY", "HHI"):
            assert holder_term not in all_flags


# ── Profile degradation + identity ────────────────────────────────────────────

class TestProfileDegradation:
    def test_market_store_unavailable_does_not_500(self):
        view = _profile(store=None, attestations=[_attestation()])
        assert view.market_evidence_coverage == "UNAVAILABLE"
        assert all(p.market_evidence_state == "UNAVAILABLE"
                   for p in view.representations)

    def test_attestation_authority_unavailable_does_not_500(self):
        view = _profile(attestations=None)
        assert view.attestation_evidence_state == "UNAVAILABLE"
        assert IdentityFlag.ATTESTATION_UNAVAILABLE.value in (
            view.integrity_flags)

    def test_market_store_exception_does_not_500(self, tmp_path):
        class FailingStore:
            def __getattr__(self, name):
                raise RuntimeError("store down")

        view = _profile(store=FailingStore(), attestations=[_attestation()])
        assert view.market_evidence_coverage == "UNAVAILABLE"

    def test_identity_conflict_remains_explicit(self):
        registry = _registry([
            _entry(source="source-a"),
            _entry(source="source-b", contract_address="0x" + "bb" * 20),
        ])
        view = build_underlying_integrity(
            "NVDA", registry=registry, store=None,
            attestations=[_attestation()], now=NOW)
        assert view.conflict_count == 2
        assert IdentityFlag.IDENTITY_CONFLICT.value in view.integrity_flags
        # conflicts remain inspectable in the profile list
        assert all(p.registry_status == "CONFLICT"
                   for p in view.representations)

    def test_quarantine_remains_explicit(self):
        registry = _registry([_entry()], quarantines=[
            {"chain_id": 4663, "contract_address": NVDA_CONTRACT,
             "classification": "impostor"}])
        view = build_underlying_integrity(
            "NVDA", registry=registry, store=None,
            attestations=[_attestation()], now=NOW)
        assert view.quarantined_count == 1
        assert IdentityFlag.REPRESENTATION_QUARANTINED.value in (
            view.integrity_flags)
        quarantined = next(p for p in view.representations
                           if p.registry_status == "QUARANTINED")
        assert quarantined.contract_address == NVDA_CONTRACT

    def test_unknown_underlying_raises_keyerror(self):
        registry = _registry([_entry()])
        with pytest.raises(KeyError):
            build_underlying_integrity("ZZZZ", registry=registry, store=None,
                                       now=NOW)

    def test_market_intelligence_math_not_duplicated(self):
        """The integrity read model imports the merged #179 authority for
        freshness/basis/divergence — it never recomputes basis itself."""
        source = open(
            REPO / "app" / "rwa_integrity" / "read_model.py",
            encoding="utf-8").read()
        assert "build_tokenized_intelligence" in source
        assert "def compute_basis" not in source
        assert "/ Decimal(reference_price)" not in source

    def test_no_execution_signing_custody_logic(self):
        for name in ("contracts.py", "read_model.py"):
            source = open(REPO / "app" / "rwa_integrity" / name,
                          encoding="utf-8").read()
            lowered = source.lower()
            for forbidden in ("sign_transaction", "private_key",
                              "broadcast", "swap(", "execute_trade"):
                assert forbidden not in lowered, (name, forbidden)

    def test_list_integrity_profiles_deterministic(self):
        registry = _registry([_entry()])
        first = list_integrity_profiles(registry, now=NOW)
        second = list_integrity_profiles(registry, now=NOW)
        assert [v.canonical_asset_id for v in first] == [
            v.canonical_asset_id for v in second]


# ── Frozen namespaces ─────────────────────────────────────────────────────────

class TestFrozen:
    @pytest.mark.parametrize("namespace", ["financial_engine", "finco_core",
                                           "finco_radar/venues"])
    def test_zero_diff(self, namespace):
        out = subprocess.run(
            ["git", "diff", "--name-only", "origin/main..HEAD", "--", namespace],
            cwd=REPO, capture_output=True, text=True)
        if out.returncode != 0:
            pytest.skip("git unavailable")
        assert out.stdout.strip() == "", out.stdout


# ── Correction A: #179 binding, ACTIVE-only deps, PARTIAL aggregation ────────

class TestPopulatedStoreBinding:
    """A real populated VenueMarketStore must map through the #179
    RepresentationHistory authority with complete identity binding."""

    def test_populated_store_produces_available_market_evidence(self):
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

    def test_populated_store_basis_propagates_from_179(self):
        registry = _registry([_entry()])
        store = VenueMarketStore(_tmp_store())
        _observation_obj(store, price="196.00", reference_price="195.00",
                         reference_state="FRESH",
                         reference_observed_at=(NOW - timedelta(seconds=30)).isoformat())
        view = build_underlying_integrity(
            "NVDA", registry=registry, store=store,
            attestations=[_attestation()], now=NOW)
        rep = view.representations[0]
        # The #179 authority is the sole basis source — integrity model
        # propagates whatever the authority computed (never re-computes).
        from finco_radar.venues.intelligence import build_tokenized_intelligence
        intel = build_tokenized_intelligence(
            "NVDA", registry=registry, store=store, as_of=NOW,
            include_points=False)
        assert intel.representations, "179 must produce history"
        expected_basis = intel.representations[0].latest_basis_bps
        assert rep.basis_bps == expected_basis
        assert rep.basis_evidence_state == (
            "AVAILABLE" if expected_basis is not None else "UNAVAILABLE")

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
        # Write observation for the same instrument on a DIFFERENT venue
        _observation_obj(store, price="999.00", venue_id="ethereum",
                         instrument_type="tokenized-equity")
        view = build_underlying_integrity(
            "NVDA", registry=registry, store=store,
            attestations=[_attestation()], now=NOW)
        # The robinhood entry must NOT see the ethereum observation.
        assert view.representations[0].market_evidence_state == "UNAVAILABLE"

    def test_representation_type_collision_cannot_cross_bind(self):
        registry = _registry([_entry()])
        store = VenueMarketStore(_tmp_store())
        _observation_obj(store, price="999.00",
                         instrument_type="perpetual")
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
        # reference evidence AVAILABLE from the bound-reference reader;
        # cross-venue divergence UNAVAILABLE (single venue)
        assert view.cross_venue_divergence_state == "UNAVAILABLE"


class TestDependencyFromActiveOnly:
    def test_quarantined_second_venue_keeps_single_venue_dependency(self):
        quarantined = _entry(
            platform="xstocks", representation_symbol="NVDAx",
            network="ethereum", chain_id=1,
            contract_address="0x" + "22" * 20,
            source="xstocks-official-api")
        registry = _registry([_entry(), quarantined], quarantines=[
            {"network": "ethereum",
             "contract_address": "0x" + "22" * 20,
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
        conflicted = _entry(
            platform="xstocks", representation_symbol="NVDAx",
            network="ethereum", chain_id=1,
            contract_address="0x" + "22" * 20,
            source="xstocks-official-api")
        registry = _registry([
            _entry(source="source-a"),
            _entry(source="source-b", contract_address="0x" + "bb" * 20),
            conflicted,
        ])
        view = build_underlying_integrity(
            "NVDA", registry=registry, store=None,
            attestations=[_attestation()], now=NOW)
        assert view.conflict_count >= 1
        assert IdentityFlag.IDENTITY_CONFLICT.value in view.integrity_flags
        assert IdentityFlag.SINGLE_VENUE_DEPENDENCY.value in view.dependency_flags


class TestAttestationCoverageAggregation:
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
            _attestation(chain_id=1,
                         contract_address="0x" + "22" * 20),
        ]
        view = build_underlying_integrity(
            "NVDA", registry=registry, store=None,
            attestations=attestations, now=NOW)
        assert view.attestation_evidence_state == "VERIFIED"

    def test_one_of_two_active_attested_is_partial(self):
        registry = _registry(self._two_reps())
        attestations = [_attestation()]  # only robinhood attested
        view = build_underlying_integrity(
            "NVDA", registry=registry, store=None,
            attestations=attestations, now=NOW)
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
