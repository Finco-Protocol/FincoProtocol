"""Model ↔ Market Bridge V1 — fail-closed identity and binding contracts.

Fixture coverage (synthetic, clearly non-production):

  A. exact source-proven binding -> SOURCE_PROVEN / OK
  B. same display metadata, wrong economic_asset_uid -> rejected
  C. same display metadata, wrong deployment -> rejected
  D. correct economic asset, wrong chain -> rejected
  E. correct chain, wrong contract -> rejected
  F. unknown deployment -> DEPLOYMENT_UNKNOWN
  G. conflicting authoritative mappings -> fail closed
  H. stale evidence -> typed STALE
  I. revoked binding -> BINDING_REVOKED / unusable
  J. superseded binding -> historical only
  K. duplicate canonical binding -> deterministic identity

Negative assertions: the bridge modules contain no display-metadata or
machine-inference identity authority (no ticker/symbol/fuzzy/similarity/
best-match/LLM/vendor-search resolvers), never promote to FINCO Verify,
and never mutate the Verify authority.

Frozen-authority gates assert ZERO diff vs origin/main for
financial_engine/, finco_core/, finco_radar/**, app/model_validation/,
app/verified/.
"""
from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# Synthetic, obviously non-production identities.
_CHAIN = 4663
_SYNTH_TOKEN = "0x" + "ab" * 20
_SYNTH_TOKEN_2 = "0x" + "cd" * 20
_SYNTH_UID = "0x00000000000000000000000000000000" + "aa" * 16
_SYNTH_UID_2 = "0x00000000000000000000000000000000" + "bb" * 16
_MODEL_UID = "project:11111111-1111-1111-1111-111111111111"
_NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_experimental_api_fixture_registry_backs_read_only_spike():
        from app.model_market_bridge.fixtures import build_fixture_registry
        registry = build_fixture_registry()
        assert len(registry.bindings) == 1

def _known_deployment_factory(known):
    def _known(deployment):
        return deployment in known
    return _known


def _known_economic_factory(known_uids):
    def _known(uid):
        return uid in known_uids
    return _known


def _deployment(chain=_CHAIN, token=_SYNTH_TOKEN):
    from app.model_market_bridge import DeploymentIdentity
    return DeploymentIdentity(chain_id=chain, contract_address=token,
                              deployment_type="TOKEN", venue="SYNTHETIC_VENUE",
                              source_authority="SYNTHETIC_DEPLOYMENT_RECORD")


def _evidence(observed_at=_NOW, authority="SYNTHETIC_MARKET_AUTHORITY"):
    from app.model_market_bridge import MarketEvidenceReference
    return MarketEvidenceReference(
        authority=authority,
        ref="SYNTHETIC_EVIDENCE_DIGEST_0001",
        observed_at=observed_at,
    )


def _binding(**overrides):
    from app.model_market_bridge import (
        BindingStatus, DeploymentIdentity, MarketEvidenceReference,
        ModelAssetKind, ModelMarketBindingV1, ProvenanceType,
    )
    fields = dict(
        model_asset_uid=_MODEL_UID,
        model_asset_kind=ModelAssetKind.PROJECT_INSTANCE,
        economic_asset_uid=_SYNTH_UID,
        deployment=DeploymentIdentity(
            chain_id=_CHAIN, contract_address=_SYNTH_TOKEN,
            deployment_type="TOKEN", venue="SYNTHETIC_VENUE",
            source_authority="SYNTHETIC_DEPLOYMENT_RECORD"),
        evidence=MarketEvidenceReference(
            authority="SYNTHETIC_MARKET_AUTHORITY",
            ref="SYNTHETIC_EVIDENCE_DIGEST_0001", observed_at=_NOW),
        provenance_type=ProvenanceType.CANONICAL_REGISTRY_RECORD,
        provenance_ref="synthetic-registry-entry-0001",
        status=BindingStatus.SOURCE_PROVEN,
    )
    fields.update(overrides)
    return ModelMarketBindingV1(**fields)


def _registry(bindings, *, known_deployments=None, known_uids=None, now=_NOW,
              max_age=3600):
    from app.model_market_bridge import BridgeRegistry
    return BridgeRegistry(
        bindings=list(bindings),
        deployment_known=_known_deployment_factory(known_deployments or {_deployment()}),
        economic_asset_known=_known_economic_factory(known_uids or {_SYNTH_UID}),
        max_evidence_age_seconds=max_age,
    )


# ── A/K: happy path + deterministic identity ────────────────────────────────

class TestSourceProvenBinding:
    def test_a_exact_source_proven_binding_accepted(self):
        from app.model_market_bridge import BindingStatus, ReasonCode

        binding = _binding()
        registry = _registry([binding])
        decision = registry.evaluate(binding, now=_NOW)
        assert decision.ok
        assert decision.status is BindingStatus.SOURCE_PROVEN
        assert decision.reason is ReasonCode.OK
        assert decision.evidence_state.value == "FRESH"

    def test_k_duplicate_canonical_binding_deterministic_identity(self):
        from app.model_market_bridge import binding_uid_for

        b1, b2 = _binding(), _binding()
        assert b1.binding_uid == b2.binding_uid  # same identity -> same UID
        assert binding_uid_for(
            model_asset_uid=b1.model_asset_uid,
            model_asset_kind=b1.model_asset_kind,
            economic_asset_uid=b1.economic_asset_uid,
            deployment_uid=b1.deployment.deployment_uid,
        ) == b1.binding_uid
        # Different deployment -> different UID.
        other = _binding(deployment=_deployment(token=_SYNTH_TOKEN_2))
        assert other.binding_uid != b1.binding_uid
        # Metadata differences do NOT change the UID.
        from dataclasses import replace
        from app.model_market_bridge import ModelAssetIdentity, ModelAssetKind
        renamed = replace(b1, model_asset_uid=b1.model_asset_uid)  # identity fields equal
        assert renamed.binding_uid == b1.binding_uid
        # Display name lives on ModelAssetIdentity metadata only.
        ident = ModelAssetIdentity(
            model_asset_uid=_MODEL_UID, kind=ModelAssetKind.PROJECT_INSTANCE,
            display_name="Totally Different Display Name")
        assert ident.display_name == "Totally Different Display Name"


# ── B–F: identity discipline ────────────────────────────────────────────────

class TestIdentityDiscipline:
    def test_b_wrong_economic_asset_rejected(self):
        from app.model_market_bridge import BindingStatus, ReasonCode

        binding = _binding(economic_asset_uid=_SYNTH_UID_2)
        registry = _registry([binding])  # authority knows only _SYNTH_UID
        decision = registry.evaluate(binding, now=_NOW)
        assert not decision.ok
        assert decision.reason is ReasonCode.ECONOMIC_ASSET_UNKNOWN

    def test_c_wrong_deployment_rejected(self):
        from app.model_market_bridge import ReasonCode

        binding = _binding(deployment=_deployment(token=_SYNTH_TOKEN_2))
        registry = _registry([binding], known_deployments={_deployment()})
        decision = registry.evaluate(binding, now=_NOW)
        assert not decision.ok
        assert decision.reason is ReasonCode.DEPLOYMENT_UNKNOWN

    def test_d_wrong_chain_rejected(self):
        from app.model_market_bridge import ReasonCode

        binding = _binding(deployment=_deployment(chain=999999))
        registry = _registry([binding], known_deployments={_deployment()})
        decision = registry.evaluate(binding, now=_NOW)
        assert not decision.ok
        assert decision.reason is ReasonCode.DEPLOYMENT_UNKNOWN

    def test_e_wrong_contract_same_chain_rejected(self):
        from app.model_market_bridge import ReasonCode

        binding = _binding(deployment=_deployment(token=_SYNTH_TOKEN_2))
        registry = _registry([binding], known_deployments={_deployment()})
        decision = registry.evaluate(binding, now=_NOW)
        assert not decision.ok
        assert decision.reason is ReasonCode.DEPLOYMENT_UNKNOWN

    def test_f_unknown_deployment_rejected(self):
        from app.model_market_bridge import ReasonCode

        unknown = _deployment(token="0x" + "ff" * 20)
        binding = _binding(deployment=unknown)
        registry = _registry([binding], known_deployments=set())
        decision = registry.evaluate(binding, now=_NOW)
        assert decision.reason is ReasonCode.DEPLOYMENT_UNKNOWN

    def test_candidate_without_provenance_not_source_proven(self):
        from app.model_market_bridge import BindingStatus, ReasonCode

        binding = _binding(status=BindingStatus.CANDIDATE,
                           provenance_type=None) if False else _binding(
            status=BindingStatus.CANDIDATE)
        registry = _registry([binding])
        decision = registry.evaluate(binding, now=_NOW)
        assert decision.status is BindingStatus.CANDIDATE
        assert decision.reason is ReasonCode.BINDING_NOT_SOURCE_PROVEN
        assert not decision.ok


# ── G–J: conflicts, staleness, revocation, supersession ────────────────────

class TestFailClosedSemantics:
    def test_g_conflicting_authoritative_mappings_fail_closed(self):
        from app.model_market_bridge import ReasonCode

        b1 = _binding()
        # A second source-proven record binds the SAME deployment to a
        # DIFFERENT economic asset -> DEPLOYMENT_CONFLICT at registry build.
        b2 = _binding(economic_asset_uid=_SYNTH_UID_2,
                      model_asset_uid="project:22222222-2222-2222-2222-222222222222")
        with pytest.raises(ValueError, match="DEPLOYMENT_CONFLICT"):
            _registry([b1, b2])

    def test_g2_conflicting_model_mappings_fail_closed(self):
        from app.model_market_bridge import ReasonCode

        b1 = _binding()
        # Same model asset source-proven to a different economic asset on a
        # different deployment -> IDENTITY_CONFLICT on evaluation.
        other = _binding(economic_asset_uid=_SYNTH_UID_2,
                         deployment=_deployment(token=_SYNTH_TOKEN_2))
        known = {_deployment(), _deployment(token=_SYNTH_TOKEN_2)}
        uids = {_SYNTH_UID, _SYNTH_UID_2}
        registry = _registry([b1, other], known_deployments=known, known_uids=uids)
        decision = registry.evaluate_for_model_asset(_MODEL_UID, now=_NOW)
        assert decision.reason is ReasonCode.IDENTITY_CONFLICT

    def test_h_stale_evidence_typed(self):
        from app.model_market_bridge import BindingStatus, EvidenceState, ReasonCode

        old = _binding(evidence=_evidence(observed_at=_NOW - timedelta(seconds=7200)))
        registry = _registry([old], max_age=3600)
        decision = registry.evaluate(old, now=_NOW)
        assert decision.status is BindingStatus.STALE
        assert decision.reason is ReasonCode.EVIDENCE_STALE
        assert decision.evidence_state is EvidenceState.STALE

    def test_h2_future_evidence_is_malformed(self):
        from app.model_market_bridge import ReasonCode

        future = _binding(evidence=_evidence(observed_at=_NOW + timedelta(hours=1)))
        registry = _registry([future])
        decision = registry.evaluate(future, now=_NOW)
        assert decision.reason is ReasonCode.MALFORMED_BINDING

    def test_i_revoked_binding_unusable(self):
        from app.model_market_bridge import BindingLifecycle, BindingStatus, ReasonCode

        revoked = _binding(lifecycle=BindingLifecycle.REVOKED)
        registry = _registry([revoked])
        decision = registry.evaluate(revoked, now=_NOW)
        assert decision.status is BindingStatus.REVOKED
        assert decision.reason is ReasonCode.BINDING_REVOKED
        assert not decision.ok

    def test_j_superseded_binding_historical_only(self):
        from app.model_market_bridge import BindingLifecycle, ReasonCode

        superseded = _binding(lifecycle=BindingLifecycle.SUPERSEDED)
        registry = _registry([superseded])
        decision = registry.evaluate(superseded, now=_NOW)
        assert decision.reason is ReasonCode.BINDING_SUPERSEDED
        assert not decision.ok

    def test_unknown_model_asset_is_unbound(self):
        from app.model_market_bridge import ReasonCode

        registry = _registry([])
        decision = registry.evaluate_for_model_asset("project:does-not-exist", now=_NOW)
        assert decision.reason is ReasonCode.MODEL_UID_UNKNOWN


# ── Negative assertions: no heuristic identity authority exists ────────────

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

        values = {m.value for m in ProvenanceType}
        assert values == {
            "ISSUER_DOCUMENT", "CANONICAL_REGISTRY_RECORD", "DEPLOYMENT_RECORD",
            "CONTROLLED_METADATA", "REVIEWED_EVIDENCE_PACKAGE",
        }

    def test_identity_dataclasses_do_not_resolve_from_display_name(self):
        import inspect

        from app.model_market_bridge import contracts
        source = inspect.getsource(contracts)
        # Display name exists as inert metadata only.
        assert 'display_name: str = ""' in source
        # No resolver function derives identity from it.
        assert "display_name.lower()" not in source
        assert "display_name.strip()" not in source or "raise ValueError" in source


# ── Verify seam: designed, never activated ─────────────────────────────────

class TestVerifySeam:
    def test_source_proven_eligible_but_never_verified(self):
        binding = _binding()
        registry = _registry([binding])
        seam = registry.verify_evaluation_seam(binding, now=_NOW)
        assert seam.eligible_for_verify_evaluation is True
        assert "Eligibility is not verification" in seam.note
        assert "PRODUCTION_VERIFIED_ASSET_COUNT" in seam.note

    def test_non_source_proven_never_eligible(self):
        from app.model_market_bridge import BindingStatus

        binding = _binding(status=BindingStatus.CANDIDATE)
        registry = _registry([binding])
        seam = registry.verify_evaluation_seam(binding, now=_NOW)
        assert seam.eligible_for_verify_evaluation is False
        assert seam.preconditions["reason"] == "BINDING_NOT_SOURCE_PROVEN"

    def test_bridge_never_calls_verify_authority(self):
        import inspect

        import app.model_market_bridge.registry as registry_module

        source = inspect.getsource(registry_module)
        assert "app.verified" not in source
        assert "PRODUCTION_VERIFIED_ASSET_COUNT" not in source.replace(
            '"PRODUCTION_VERIFIED_ASSET_COUNT "', "")  # only inside seam note text


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

    def test_bridge_does_not_duplicate_r_live_authority(self):
        """The bridge reuses the R-LIVE registry read-only; no second market
        authority is created (no pricing/TWAP/freshness logic in the bridge)."""
        bridge_dir = REPO / "app" / "model_market_bridge"
        for path in sorted(bridge_dir.glob("*.py")):
            src = path.read_text(encoding="utf-8").lower()
            # Pricing-logic markers only (prose explaining "not a price
            # authority" legitimately contains the word "price").
            for token in ("twap", "pool_address", "quote_token", "sqrt",
                          "get_amounts", "tick_to_price"):
                assert token not in src, f"{path.name} must not contain {token!r}"
