"""Model ↔ Market Bridge V1 — Correction A fail-closed contracts.

Fixture coverage (synthetic, clearly non-production):

  A. exact attested (economic_asset_uid ↔ deployment) pairing, source-proven
     -> SOURCE_PROVEN / OK
  B. valid economic UID + valid deployment that are NOT attested as a pair
     -> PAIRING_MISMATCH (BLOCKER 1: no independent existence acceptance)
  B2. unknown economic UID -> ECONOMIC_ASSET_UNKNOWN
  C. unknown deployment -> DEPLOYMENT_UNKNOWN
  D. duplicate canonical binding with materially conflicting records ->
     IDENTITY_CONFLICT (fail closed, no silent overwrite)
  E. stale evidence state produced by the market authority -> typed STALE
  F. revoked binding -> unusable; superseded binding -> historical only
  G. deterministic binding UID; economic uid VERBATIM (no case folding)
  H. exact EVM address contract (0x + exactly 40 hex); rejects bare 0x,
     short, long, non-hex
  I. evidence state consumed from the authority — no bridge-side generic
     freshness computation

Negative assertions: no display-metadata or machine-inference identity
authority in the bridge modules; no Verify promotion; no pricing logic.
Frozen-authority gates assert ZERO diff vs origin/main.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

_CHAIN = 4663
_TOKEN = "0x" + "ab" * 20
_TOKEN_B = "0x" + "cd" * 20
_UID = "0x00000000000000000000000000000000" + "aa" * 16
_UID_B = "0x00000000000000000000000000000000" + "bb" * 16
_MODEL = "project:11111111-1111-1111-1111-111111111111"
_NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)


def _dep(token: str = _TOKEN, chain: int = _CHAIN):
    from app.model_market_bridge import DeploymentIdentity
    return DeploymentIdentity(
        chain_id=chain, contract_address=token, deployment_type="TOKEN",
        venue="SYNTHETIC_VENUE", source_authority="SYNTHETIC_DEPLOYMENT_RECORD")


@dataclass(frozen=True)
class _Pairing:
    """Synthetic pairing authority over attested (uid, dep_uid) tuples."""
    attested: frozenset
    known_uids: frozenset
    known_deps: frozenset

    def __call__(self, uid, deployment):
        from app.model_market_bridge import ReasonCode
        if (uid, deployment.deployment_uid) in self.attested:
            return ReasonCode.OK
        if uid in self.known_uids and deployment.deployment_uid in self.known_deps:
            return ReasonCode.PAIRING_MISMATCH
        if uid not in self.known_uids:
            return ReasonCode.ECONOMIC_ASSET_UNKNOWN
        return ReasonCode.DEPLOYMENT_UNKNOWN


def _pairing(attested=None, known_uids=None, known_deps=None):
    """Synthetic pairing authority over attested (uid, dep_uid) tuples."""
    attested = attested if attested is not None else {(_UID, _dep().deployment_uid)}
    known_uids = known_uids if known_uids is not None else {_UID, _UID_B}
    known_deps = known_deps if known_deps is not None else {
        _dep().deployment_uid, _dep(_TOKEN_B).deployment_uid}

    def _pairing(uid, deployment):
        from app.model_market_bridge import ReasonCode
        if (uid, deployment.deployment_uid) in attested:
            return ReasonCode.OK
        if uid in known_uids and deployment.deployment_uid in known_deps:
            return ReasonCode.PAIRING_MISMATCH
        if uid not in known_uids:
            return ReasonCode.ECONOMIC_ASSET_UNKNOWN
        return ReasonCode.DEPLOYMENT_UNKNOWN
    return _Pairing(
        attested=frozenset(attested),
        known_uids=frozenset(known_uids),
        known_deps=frozenset(known_deps),
    )


def _fresh_authority(stale_for=None):
    """Test-local evidence-state authority (synthetic freshness)."""
    from app.model_market_bridge import EvidenceState

    def _state(binding):
        if stale_for is not None and binding.evidence.observed_at < stale_for:
            return EvidenceState.STALE
        return EvidenceState.FRESH
    return _state


def _unavailable_authority():
    from app.model_market_bridge import EvidenceState
    return lambda binding: EvidenceState.UNAVAILABLE


def _binding(**overrides):
    from app.model_market_bridge import (
        BindingStatus, DeploymentIdentity, EvidenceState,
        MarketEvidenceReference, ModelAssetKind, ModelMarketBindingV1,
        ProvenanceType,
    )
    fields = dict(
        model_asset_uid=_MODEL,
        model_asset_kind=ModelAssetKind.PROJECT_INSTANCE,
        economic_asset_uid=_UID,
        deployment=_dep(),
        evidence=MarketEvidenceReference(
            authority="SYNTHETIC_MARKET_AUTHORITY",
            ref="SYNTHETIC_EVIDENCE_DIGEST_0001",
            observed_at=_NOW,
            state=EvidenceState.FRESH),
        provenance_type=ProvenanceType.CANONICAL_REGISTRY_RECORD,
        provenance_ref="synthetic-registry-entry-0001",
        status=BindingStatus.SOURCE_PROVEN,
    )
    fields.update(overrides)
    return ModelMarketBindingV1(**fields)


def _registry(bindings, pairing=None, evidence=None):
    from app.model_market_bridge import BridgeRegistry
    return BridgeRegistry(
        bindings=list(bindings),
        pairing_authority=pairing or _pairing(),
        evidence_state_authority=evidence or _fresh_authority(),
    )


# ── A: exact attested pairing, source-proven ───────────────────────────────

class TestSourceProvenPairing:
    def test_a_attested_pairing_accepted(self):
        from app.model_market_bridge import BindingStatus, EvidenceState, ReasonCode

        binding = _binding()
        decision = _registry([binding]).evaluate(binding, now=_NOW)
        assert decision.ok
        assert decision.status is BindingStatus.SOURCE_PROVEN
        assert decision.reason is ReasonCode.OK
        assert decision.evidence_state is EvidenceState.FRESH

    def test_k_duplicate_canonical_binding_deterministic_uid(self):
        from app.model_market_bridge import binding_uid_for

        b1, b2 = _binding(), _binding()
        assert b1.binding_uid == b2.binding_uid
        assert binding_uid_for(
            model_asset_uid=b1.model_asset_uid,
            model_asset_kind=b1.model_asset_kind,
            economic_asset_uid=b1.economic_asset_uid,
            deployment_uid=b1.deployment.deployment_uid,
        ) == b1.binding_uid
        other_dep = _binding(deployment=_dep(token=_TOKEN_B))
        assert other_dep.binding_uid != b1.binding_uid

    def test_two_active_proven_bindings_for_one_model_fail_closed(self):
        from app.model_market_bridge import ReasonCode

        b1 = _binding()
        b2 = _binding(economic_asset_uid=_UID_B, deployment=_dep(token=_TOKEN_B))
        # Both tuples individually attested -> both proven -> one model asset
        # with two conflicting source-proven identities fails closed.
        attested = {
            (_UID, _dep().deployment_uid),
            (_UID_B, _dep(_TOKEN_B).deployment_uid),
        }
        registry = _registry(
            [b1, b2],
            pairing=_pairing(
                attested=attested, known_uids={_UID, _UID_B},
                known_deps={_dep().deployment_uid, _dep(_TOKEN_B).deployment_uid}),
        )
        decision = registry.evaluate_for_model_asset(_MODEL, now=_NOW)
        assert decision.reason is ReasonCode.IDENTITY_CONFLICT


# ── BLOCKER 1: pairwise authority ───────────────────────────────────────────

class TestPairwiseEconomicAssetDeploymentAuthority:
    def test_b1_valid_uid_plus_valid_unpaired_deployment_fails_closed(self):
        """BLOCKER 1 regression: a valid economic UID from asset A must never
        be accepted with a valid deployment from asset B merely because both
        exist independently.  Synthetic equivalent of AAPL UID + NVDA
        deployment: both sides canonical, pairing absent -> fail closed."""
        from app.model_market_bridge import ReasonCode

        binding = _binding(economic_asset_uid=_UID, deployment=_dep(token=_TOKEN_B))
        decision = _registry([binding]).evaluate(binding, now=_NOW)
        assert not decision.ok
        assert decision.reason is ReasonCode.PAIRING_MISMATCH
        # The mirror: asset-B uid with the asset-A deployment also fails.
        mirror = _binding(economic_asset_uid=_UID_B)
        mirror_decision = _registry([mirror]).evaluate(mirror, now=_NOW)
        assert mirror_decision.reason is ReasonCode.PAIRING_MISMATCH

    def test_b2_unknown_economic_uid_fails_closed(self):
        from app.model_market_bridge import ReasonCode

        unknown_uid = _binding(economic_asset_uid="0x" + "ee" * 16)
        decision = _registry([unknown_uid]).evaluate(unknown_uid, now=_NOW)
        assert decision.reason is ReasonCode.ECONOMIC_ASSET_UNKNOWN

    def test_c_unknown_deployment_fails_closed(self):
        from app.model_market_bridge import ReasonCode

        unknown = _dep(token="0x" + "ff" * 20)
        binding = _binding(deployment=unknown)
        decision = _registry(
            [binding], pairing=_pairing(known_deps=set())).evaluate(binding, now=_NOW)
        assert decision.reason is ReasonCode.DEPLOYMENT_UNKNOWN

    def test_r_live_pairing_authority_proves_exact_tuples(self):
        """The production adapter proves real R-LIVE tuples and rejects
        cross-asset pairings (first uid + second asset deployment)."""
        from app.model_market_bridge import ReasonCode, r_live_pairing_authority
        from finco_radar.authority.r_live_policy import (
            APPROVED_BY_CANONICAL_ID, AssetKey,
        )

        authority = r_live_pairing_authority()
        policies = list(APPROVED_BY_CANONICAL_ID.values())
        assert len(policies) >= 2, "R-LIVE reviewed universe must have 2+ assets"
        first, second = policies[0], policies[1]

        paired = _dep_from_asset_key(first.asset_key)
        assert authority(first.economic_asset_uid, paired) is ReasonCode.OK
        cross = _dep_from_asset_key(second.asset_key)
        assert authority(first.economic_asset_uid, cross) is ReasonCode.PAIRING_MISMATCH
        unknown = _dep_from_asset_key(AssetKey(_CHAIN, "0x" + "ff" * 20))
        assert authority(first.economic_asset_uid, unknown) is ReasonCode.DEPLOYMENT_UNKNOWN

    def test_no_generic_freshness_authority_in_registry(self):
        """BLOCKER 4: the registry consumes authority-produced evidence
        states; no generic bridge-side freshness computation exists."""
        import inspect

        from app.model_market_bridge import BridgeRegistry
        source = inspect.getsource(BridgeRegistry)
        assert "max_evidence_age_seconds" not in source
        params = inspect.signature(BridgeRegistry).parameters
        assert "evidence_state_authority" in params


def _dep_from_asset_key(asset_key):
    from app.model_market_bridge import DeploymentIdentity
    return DeploymentIdentity(
        chain_id=asset_key.chain_id,
        contract_address=str(asset_key.contract_address),
        deployment_type="TOKEN",
        venue="UNISWAP_V3_ROBINHOOD_CHAIN",
        source_authority="R_LIVE_REVIEWED_REGISTRY",
    )


# ── BLOCKER 2: exact EVM address contract ──────────────────────────────────

class TestEvmAddressContract:
    def test_valid_address_canonicalizes_to_lower(self):
        from app.model_market_bridge import canonical_evm_address

        assert canonical_evm_address("0x" + "AB" * 20) == "0x" + "ab" * 20

    @pytest.mark.parametrize("bad", [
        "0x",                                # bare prefix
        "0x" + "ab" * 19,                    # short (38 hex)
        "0x" + "ab" * 21,                    # long (42 hex)
        "0x" + "xy" * 20,                    # non-hex
        "ab" * 20,                           # missing prefix
        "",                                  # empty
    ])
    def test_invalid_addresses_rejected(self, bad):
        from app.model_market_bridge import DeploymentIdentity, canonical_evm_address

        with pytest.raises(ValueError):
            canonical_evm_address(bad)
        with pytest.raises(ValueError):
            _dep(token=bad)

    def test_address_resemblance_never_repaired_into_identity(self):
        from app.model_market_bridge import DeploymentIdentity

        for bad in ("0x" + "ab" * 19, "0x" + "ab" * 21, "0x"):
            with pytest.raises(ValueError):
                DeploymentIdentity(chain_id=_CHAIN, contract_address=bad)


# ── BLOCKER 3: economic uid VERBATIM ───────────────────────────────────────

class TestEconomicUidVerbatim:
    def test_uid_case_is_never_folded_in_binding_uid(self):
        from app.model_market_bridge import ModelAssetKind, binding_uid_for

        lower = "0x" + "aa" * 16
        upper = "0X" + "AA" * 16
        u_lower = binding_uid_for(
            model_asset_uid=_MODEL, model_asset_kind=ModelAssetKind.PROJECT_INSTANCE,
            economic_asset_uid=lower, deployment_uid="dep_x")
        u_upper = binding_uid_for(
            model_asset_uid=_MODEL, model_asset_kind=ModelAssetKind.PROJECT_INSTANCE,
            economic_asset_uid=upper, deployment_uid="dep_x")
        assert u_lower != u_upper, "verbatim uid: case must never be folded"

    def test_uid_stored_verbatim(self):
        from app.model_market_bridge import EconomicAssetIdentity

        verbatim = "  " + _UID  # only the non-empty check applies
        ident = EconomicAssetIdentity(economic_asset_uid=verbatim)
        assert ident.economic_asset_uid == verbatim


# ── BLOCKER 4: evidence state consumed from the authority ─────────────────

class TestEvidenceStateFromAuthority:
    def test_stale_state_produced_by_authority_is_typed(self):
        from app.model_market_bridge import BindingStatus, EvidenceState, ReasonCode

        binding = _binding(evidence=_evidence_observed(
            _NOW - timedelta(seconds=7200)))
        registry = _registry([binding], evidence=_fresh_authority(
            stale_for=_NOW - timedelta(seconds=3600)))
        decision = registry.evaluate(binding, now=_NOW)
        assert decision.status is BindingStatus.STALE
        assert decision.reason is ReasonCode.EVIDENCE_STALE
        assert decision.evidence_state is EvidenceState.STALE

    def test_unavailable_state_produced_by_authority_is_typed(self):
        from app.model_market_bridge import ReasonCode

        binding = _binding()
        registry = _registry([binding], evidence=_unavailable_authority())
        decision = registry.evaluate(binding, now=_NOW)
        assert decision.reason is ReasonCode.EVIDENCE_UNAVAILABLE

    def test_no_generic_freshness_authority_on_registry(self):
        import inspect

        from app.model_market_bridge import BridgeRegistry
        params = inspect.signature(BridgeRegistry).parameters
        assert "max_evidence_age_seconds" not in params
        assert "evidence_state_authority" in params


def _evidence_observed(observed_at):
    from app.model_market_bridge import EvidenceState, MarketEvidenceReference

    return MarketEvidenceReference(
        authority="SYNTHETIC_MARKET_AUTHORITY",
        ref="SYNTHETIC_EVIDENCE_DIGEST_0001",
        observed_at=observed_at,
        state=EvidenceState.FRESH,  # constructor state; authority verdict rules
    )


# ── D: duplicate records fail closed on material conflict ─────────────────

class TestDuplicateRecordSemantics:
    def test_identical_duplicates_collapse(self):
        b1, b2 = _binding(), _binding()
        registry = _registry([b1, b2])
        assert registry.get_by_uid(b1.binding_uid) is not None

    def test_status_conflict_fails_closed(self):
        from app.model_market_bridge import BindingStatus

        b1 = _binding()
        b2 = _binding(status=BindingStatus.CANDIDATE)  # same uid, different status
        with pytest.raises(ValueError, match="IDENTITY_CONFLICT"):
            _registry([b1, b2])

    def test_evidence_conflict_fails_closed(self):
        b1 = _binding()
        b2 = _binding(evidence=_evidence_observed(_NOW + timedelta(seconds=5)))
        with pytest.raises(ValueError, match="IDENTITY_CONFLICT"):
            _registry([b1, b2])


# ── Lifecycle semantics ─────────────────────────────────────────────────────

class TestLifecycleSemantics:
    def test_revoked_binding_unusable(self):
        from app.model_market_bridge import BindingLifecycle, BindingStatus, ReasonCode

        revoked = _binding(lifecycle=BindingLifecycle.REVOKED)
        decision = _registry([revoked]).evaluate(revoked, now=_NOW)
        assert decision.status is BindingStatus.REVOKED
        assert decision.reason is ReasonCode.BINDING_REVOKED

    def test_superseded_binding_historical_only(self):
        from app.model_market_bridge import BindingLifecycle, ReasonCode

        superseded = _binding(lifecycle=BindingLifecycle.SUPERSEDED)
        decision = _registry([superseded]).evaluate(superseded, now=_NOW)
        assert decision.reason is ReasonCode.BINDING_SUPERSEDED
        assert not decision.ok

    def test_unknown_model_asset_unbound(self):
        from app.model_market_bridge import ReasonCode

        decision = _registry([]).evaluate_for_model_asset("project:nope", now=_NOW)
        assert decision.reason is ReasonCode.MODEL_UID_UNKNOWN


# ── Verify seam: designed, never activated ─────────────────────────────────

class TestVerifySeam:
    def test_source_proven_eligible_but_never_verified(self):
        binding = _binding()
        seam = _registry([binding]).verify_evaluation_seam(binding, now=_NOW)
        assert seam.eligible_for_verify_evaluation is True
        assert "Eligibility is not verification" in seam.note
        assert "PRODUCTION_VERIFIED_ASSET_COUNT" in seam.note

    def test_candidate_never_eligible(self):
        from app.model_market_bridge import BindingStatus

        binding = _binding(status=BindingStatus.CANDIDATE)
        seam = _registry([binding]).verify_evaluation_seam(binding, now=_NOW)
        assert seam.eligible_for_verify_evaluation is False
        assert seam.preconditions["reason"] == "BINDING_NOT_SOURCE_PROVEN"


# ── Negative source assertions ─────────────────────────────────────────────

class TestNoHeuristicIdentityAuthority:
    def test_bridge_modules_contain_no_display_metadata_resolvers(self):
        bridge_dir = REPO / "app" / "model_market_bridge"
        banned = (
            "fuzzy", "similarity", "best_match", "best match", "levenshtein",
            "difflib", "openai", "google", "yahoo", "ticker_match",
            "name_match", "llm", "gpt",
        )
        for path in sorted(bridge_dir.glob("*.py")):
            src = path.read_text(encoding="utf-8").lower()
            for token in banned:
                assert token not in src, f"{path.name} contains banned token {token!r}"

    def test_provenance_enum_has_no_heuristic_members(self):
        from app.model_market_bridge import ProvenanceType

        assert {m.value for m in ProvenanceType} == {
            "ISSUER_DOCUMENT", "CANONICAL_REGISTRY_RECORD", "DEPLOYMENT_RECORD",
            "CONTROLLED_METADATA", "REVIEWED_EVIDENCE_PACKAGE",
        }

    def test_bridge_does_not_duplicate_market_authority_logic(self):
        bridge_dir = REPO / "app" / "model_market_bridge"
        for path in sorted(bridge_dir.glob("*.py")):
            src = path.read_text(encoding="utf-8").lower()
            for token in ("twap", "pool_address", "quote_token", "sqrt",
                          "max_evidence_age_seconds"):
                assert token not in src, f"{path.name} must not contain {token!r}"

    def test_bridge_never_calls_verify_authority(self):
        import inspect

        import app.model_market_bridge.registry as registry_module

        source = inspect.getsource(registry_module)
        assert "app.verified" not in source
        assert "PRODUCTION_VERIFIED_ASSET_COUNT" not in source

    def test_model_uid_helpers_never_use_display_names(self):
        import inspect

        from app.model_market_bridge import contracts
        source = inspect.getsource(contracts)
        assert 'display_name: str = ""' in source
        assert "display_name.lower()" not in source


# ── BLOCKER 5: default-off API + bounded validate ─────────────────────────

class TestExperimentalApiSurface:
    @pytest.fixture()
    def client(self):
        import os
        import tempfile

        os.environ["FINCO_DB_PATH"] = os.path.join(
            tempfile.mkdtemp(), "bridge-api.db")
        from fastapi.testclient import TestClient
        import main_api

        return TestClient(main_api.app)

    def test_api_disabled_by_default(self, client, monkeypatch):
        monkeypatch.delenv("FINCO_MODEL_MARKET_BRIDGE_API_ENABLED", raising=False)
        r = client.get("/api/v1.1/model-market-bindings/whatever")
        assert r.status_code == 404
        assert r.json()["error"] == "SURFACE_DISABLED"
        r2 = client.post("/api/v1.1/model-market-bindings/validate", json={})
        assert r2.status_code == 404

    def test_api_enabled_flag_gates_surface(self, client, monkeypatch):
        monkeypatch.setenv("FINCO_MODEL_MARKET_BRIDGE_API_ENABLED", "1")
        r = client.get(
            "/api/v1.1/model-market-bindings/"
            "project:11111111-1111-1111-1111-111111111111")
        assert r.status_code == 200
        assert r.json()["decision"]["status"] == "SOURCE_PROVEN"
        assert r.json()["read_only"] is True

    def test_validate_is_bounded_and_sanitized(self, client, monkeypatch):
        monkeypatch.setenv("FINCO_MODEL_MARKET_BRIDGE_API_ENABLED", "1")
        good = {
            "model_asset_uid": _MODEL, "model_asset_kind": "PROJECT_INSTANCE",
            "economic_asset_uid": _UID, "chain_id": _CHAIN,
            "contract_address": _TOKEN, "market_evidence_authority": "SYN",
            "market_evidence_ref": "DIGEST", "observed_at": "2026-10-01T12:00:00Z",
            "provenance_type": "CANONICAL_REGISTRY_RECORD", "provenance_ref": "ref-1",
        }
        r = client.post("/api/v1.1/model-market-bindings/validate", json=good)
        assert r.status_code == 200 and r.json()["valid"] is True

        bad_field = dict(good, sneaky_extra="1")
        r2 = client.post("/api/v1.1/model-market-bindings/validate", json=bad_field)
        assert r2.json()["valid"] is False and "unknown fields" in r2.json()["detail"]

        big = dict(good, provenance_ref="x" * 9999)
        r3 = client.post("/api/v1.1/model-market-bindings/validate", json=big)
        assert r3.json()["valid"] is False and "size limit" in r3.json()["detail"]

        r4 = client.post("/api/v1.1/model-market-bindings/validate",
                         content=b"not json",
                         headers={"Content-Type": "application/json"})
        assert r4.status_code == 200
        assert r4.json()["valid"] is False
        assert r4.json()["detail"] == "request body must be a JSON object"

        bad_addr = dict(good, contract_address="0xshort")
        r5 = client.post("/api/v1.1/model-market-bindings/validate", json=bad_addr)
        assert r5.json()["valid"] is False

    def test_validate_never_produces_source_proven(self, client, monkeypatch):
        monkeypatch.setenv("FINCO_MODEL_MARKET_BRIDGE_API_ENABLED", "1")
        good = {
            "model_asset_uid": _MODEL, "model_asset_kind": "PROJECT_INSTANCE",
            "economic_asset_uid": _UID, "chain_id": _CHAIN,
            "contract_address": _TOKEN, "market_evidence_authority": "SYN",
            "market_evidence_ref": "DIGEST", "observed_at": "2026-10-01T12:00:00Z",
            "provenance_type": "CANONICAL_REGISTRY_RECORD", "provenance_ref": "ref-1",
        }
        r = client.post("/api/v1.1/model-market-bindings/validate", json=good)
        assert r.json()["status"] == "CANDIDATE"
        assert "promoted to FINCO Verify" in r.json()["note"]


# ── Frozen authorities ──────────────────────────────────────────────────────

class TestFrozenAuthorities:
    @pytest.mark.parametrize("frozen", [
        "financial_engine", "finco_core", "finco_radar",
        "app/model_validation", "app/verified",
    ])
    def test_zero_diff_vs_main(self, frozen):
        import subprocess

        out = subprocess.run(
            ["git", "diff", "--name-only", "origin/main..HEAD", "--", frozen],
            cwd=REPO, capture_output=True, text=True,
        )
        if out.returncode != 0:
            pytest.skip("git history unavailable in this checkout")
        assert out.stdout.strip() == "", out.stdout
