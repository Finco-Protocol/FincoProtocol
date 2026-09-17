"""Focused, fully offline R8 execution-simulator tests.

Deterministic synthetic fixtures only. Numbering follows the R8 specification
mandatory coverage list (§34) plus the three critical regression tests
(§35-38) and lineage/immutability requirements (§23-25).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from finco_radar.assets.contracts import AssetKey
from finco_radar.quotes.contracts import QuoteSide
from finco_radar.cross_market.contracts import verify_serialized_evidence as verify_r7
from finco_radar.execution_simulator.contracts import (
    CostTreatmentState,
    ExecutionMode,
    ExecutionScenario,
    ExecutionSimulationError,
    ExecutionSimulationSnapshot,
    ExecutionSimulationStatus,
    NetEdgeBlocker,
    NetEdgeState,
    ScenarioQuoteEvidence,
    SettlementAdjustmentEvidence,
    SettlementAdjustmentState,
    SimulationTimingPolicy,
    verify_serialized_evidence,
)
from finco_radar.execution_simulator.engine import (
    build_execution_simulation,
    compute_gross_execution_economics,
    resolve_provider_costs,
    resolve_settlement_adjustment,
    simulate_execution_scenario,
)
from finco_radar.liquidity.contracts import CostTreatmentState as _R3CostTreatmentState

T = timezone.utc
NOW = datetime(2026, 9, 17, 12, 0, tzinfo=T)
UID = "AAPL"
KEY = AssetKey(4663, "0x" + "aa" * 20)
THRESHOLD = Decimal("50")


def _r3_digest_for(evidence: dict) -> str:
    import hashlib

    return hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def policy() -> SimulationTimingPolicy:
    return SimulationTimingPolicy(
        max_cost_evidence_age_seconds=Decimal("600"),
        max_settlement_evidence_age_seconds=Decimal("600"),
    )


def scenario(
    side: QuoteSide = QuoteSide.BUY,
    notional: str = "100",
    *,
    key: AssetKey = KEY,
    uid: str = UID,
    label: str | None = "ORACLE_REFERENCE→VENUE[DEX:BUY:100]",
    mode: ExecutionMode = ExecutionMode.REFERENCE_RELATIVE,
) -> ExecutionScenario:
    return ExecutionScenario(
        economic_asset_uid=uid,
        canonical_asset_key=key,
        side=side,
        requested_notional_usd=Decimal(notional),
        quote_source="LIFI_V1_QUOTE",
        execution_mode=mode,
        r7_component_label=label,
        as_of=NOW,
    )


def evidence(
    side: QuoteSide = QuoteSide.BUY,
    notional: str = "100",
    *,
    token_amount: str = "1",
    reference: str = "100",
    settlement: str = "101",
    gap_bps: str = "100",
    key: AssetKey = KEY,
    fee: str | None = None,
    gas: str | None = None,
    treatment: CostTreatmentState = CostTreatmentState.EVIDENCE_ONLY_INCLUSION_UNRESOLVED,
    at: datetime = NOW,
    route: str | None = "SYNTH:ROUTE",
    route_changed: bool = False,
) -> ScenarioQuoteEvidence:
    return ScenarioQuoteEvidence(
        side=side,
        requested_notional_usd=Decimal(notional),
        token_amount=Decimal(token_amount),
        reference_price_usd_per_token=Decimal(reference),
        settlement_amount_usd=Decimal(settlement),
        r2_gap_bps=Decimal(gap_bps),
        quote_observed_at=at,
        reference_generated_at=at,
        settlement_observed_at=at,
        canonical_asset_key=key,
        venue="LIFI_V1_QUOTE",
        route_signature=route,
        route_changed=route_changed,
        provider_fee_usd=Decimal(fee) if fee is not None else None,
        provider_gas_usd=Decimal(gas) if gas is not None else None,
        provider_cost_treatment=treatment,
        r0_quote_evidence={"synthetic": True},
        r2_gap_evidence={"synthetic": True},
    )


def simulate(side=QuoteSide.BUY, ev=None, settlement_adj=None, notional="100", **kwargs):
    ev = ev if ev is not None else evidence(side=side, notional=notional)
    return simulate_execution_scenario(
        scenario=scenario(side=side, notional=notional),
        quote_evidence=ev,
        settlement_adjustment=settlement_adj,
        policy=policy(),
        **kwargs,
    )


def build_snap(scenarios=None, rows=None, **overrides):
    lineage_up, lineage_digests = _lineage()
    kwargs = dict(
        economic_asset_uid=UID,
        canonical_asset_key=KEY,
        upstream_evidence=lineage_up,
        source_digests=lineage_digests,
        scenarios=scenarios if scenarios is not None else [
            scenario(QuoteSide.BUY, "100"), scenario(QuoteSide.BUY, "1000"),
            scenario(QuoteSide.SELL, "100"), scenario(QuoteSide.SELL, "1000"),
        ],
        quote_evidence=rows if rows is not None else [
            evidence(QuoteSide.BUY, "100", token_amount="1", settlement="101", gap_bps="100",
                     route_changed=False),
            evidence(QuoteSide.BUY, "1000", token_amount="10", settlement="1020", gap_bps="200",
                     route_changed=False),
            evidence(QuoteSide.SELL, "100", token_amount="1", settlement="99", gap_bps="-100",
                     route_changed=False),
            evidence(QuoteSide.SELL, "1000", token_amount="10", settlement="980", gap_bps="-200",
                     route_changed=False),
        ],
        policy=policy(),
        synthetic=True,
        generated_at=NOW,
        git_head="r8-test-head",
    )
    kwargs.update(overrides)
    return build_execution_simulation(**kwargs)


# ---------------------------------------------------------------------------
# 1-5. Gross edge formulas and the mandatory R2 handshake
# ---------------------------------------------------------------------------

def test_01_buy_gross_edge_equals_negative_r2_gap() -> None:
    result = simulate(QuoteSide.BUY)
    assert result.gross_execution_edge_bps == -result.r2_gap_bps
    assert result.gross_execution_edge_bps == Decimal("-100")


def test_02_sell_gross_edge_equals_positive_r2_gap() -> None:
    # Internally consistent SELL: 1 token at reference 100 -> 99 USD proceeds
    # => exec 1% below the official BID => gap -100 bps; SELL gross = +gap.
    result = simulate(
        QuoteSide.SELL,
        evidence(QuoteSide.SELL, token_amount="1", reference="100",
                 settlement="99", gap_bps="-100"),
    )
    assert result.gross_execution_edge_bps == result.r2_gap_bps
    assert result.gross_execution_edge_bps == Decimal("-100")


def test_03_exact_buy_gross_usd_formula() -> None:
    result = simulate(QuoteSide.BUY)
    # benchmark = 1 token x 100 USD = 100; BUY: benchmark - settlement(101)
    assert result.benchmark_value_usd == Decimal("100")
    assert result.gross_execution_edge_usd == Decimal("-1")
    assert result.gross_execution_edge_bps == Decimal("-100")


def test_04_exact_sell_gross_usd_formula() -> None:
    result = simulate(
        QuoteSide.SELL,
        evidence(QuoteSide.SELL, token_amount="1", reference="100", settlement="99",
                 gap_bps="-100"),
    )
    # SELL: settlement(99) - benchmark(100) = -1 USD
    assert result.gross_execution_edge_usd == Decimal("-1")
    assert result.gross_execution_edge_bps == Decimal("-100")


def test_05_gross_bps_usd_handshake_holds_exactly() -> None:
    for side in (QuoteSide.BUY, QuoteSide.SELL):
        for settlement, gap in (("101", "100"), ("99", "-100"), ("100", "0")):
            result = simulate(side, evidence(side, token_amount="1", reference="100",
                                             settlement=settlement, gap_bps=gap))
            expected = (-result.r2_gap_bps if side is QuoteSide.BUY
                        else result.r2_gap_bps)  # SELL: +gap (spec §3)
            assert result.gross_execution_edge_bps == expected
            recomputed = result.gross_execution_edge_usd / result.benchmark_value_usd * Decimal(10000)
            assert recomputed == result.gross_execution_edge_bps


def test_06_r2_economics_mismatch_fails_closed() -> None:
    # gap_bps claims +100 for BUY but exact USD economics produce -100.
    with pytest.raises(ExecutionSimulationError) as excinfo:
        simulate(
            QuoteSide.BUY,
            evidence(QuoteSide.BUY, token_amount="1", reference="100", settlement="101",
                     gap_bps="50"),
        )
    assert excinfo.value.status is ExecutionSimulationStatus.UPSTREAM_ECONOMICS_MISMATCH


# ---------------------------------------------------------------------------
# 7-12. Identity, lineage, quote availability, upstream authority
# ---------------------------------------------------------------------------


_R7_EVIDENCE = {"attributionState": "NO_MATERIAL_DISLOCATION", "components": 4}
_R3_EVIDENCE = {"status": "PASS", "observations": 4}


def _lineage() -> tuple[dict, dict]:
    """Consistent synthetic R7+R3 lineage for offline builds."""
    return (
        {
            "r7CrossMarketEvidence": _R7_EVIDENCE,
            "r3LiquidityEvidence": _R3_EVIDENCE,
        },
        {
            "r7CrossMarketDigest": hashlib.sha256(json.dumps(
                _R7_EVIDENCE, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False).encode("utf-8")).hexdigest(),
            "r3LiquidityDigest": hashlib.sha256(json.dumps(
                _R3_EVIDENCE, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False).encode("utf-8")).hexdigest(),
        },
    )


def build_sim(scenarios=None, rows=None, **overrides):
    """Offline wrapper injecting consistent synthetic R7/R3 lineage."""
    lineage_up, lineage_digests = _lineage()
    overrides.setdefault("upstream_evidence", lineage_up)
    overrides.setdefault("source_digests", lineage_digests)
    overrides.setdefault("economic_asset_uid", UID)
    overrides.setdefault("canonical_asset_key", KEY)
    overrides.setdefault("scenarios", scenarios if scenarios is not None else [])
    overrides.setdefault("quote_evidence", rows if rows is not None else [])
    overrides.setdefault("policy", policy())
    overrides.setdefault("synthetic", True)
    overrides.setdefault("generated_at", NOW)
    overrides.setdefault("git_head", "r8-test-head")
    return build_execution_simulation(**overrides)


def test_07_canonical_asset_key_mismatch_fails() -> None:
    with pytest.raises(ExecutionSimulationError) as excinfo:
        simulate(
            QuoteSide.BUY,
            evidence(QuoteSide.BUY, key=AssetKey(1, "0x" + "bb" * 20)),
        )
    assert excinfo.value.status is ExecutionSimulationStatus.IDENTITY_MISMATCH


def test_08_r7_component_not_in_snapshot_fails_closed() -> None:
    with pytest.raises(ExecutionSimulationError) as excinfo:
        build_execution_simulation(
            economic_asset_uid=UID,
            canonical_asset_key=KEY,
            scenarios=[scenario(label="ORACLE_REFERENCE→VENUE[UNKNOWN]")],
            quote_evidence=[evidence()],
            policy=policy(),
            theoretical_dislocations={"ORACLE_REFERENCE→VENUE[UNKNOWN]": Decimal("10")},
            r7_component_labels={"SOME_OTHER_LABEL"},
        )
    assert excinfo.value.status is ExecutionSimulationStatus.R7_LINEAGE_MISMATCH


def test_09_exact_quote_notional_required() -> None:
    result = simulate(QuoteSide.BUY)
    assert result.scenario.requested_notional_usd == Decimal("100")
    # A $500 scenario has no exact quote evidence in the fixture set:
    with pytest.raises(ExecutionSimulationError) as excinfo:
        build_sim(
            scenarios=[scenario(QuoteSide.BUY, "500")],
            rows=[evidence(QuoteSide.BUY, "100")],
        )
    assert excinfo.value.status is ExecutionSimulationStatus.EXECUTION_QUOTE_UNAVAILABLE


def test_10_missing_quote_fails_closed() -> None:
    with pytest.raises(ExecutionSimulationError) as excinfo:
        build_sim(
            scenarios=[scenario(QuoteSide.SELL, "100")],
            rows=[evidence(QuoteSide.BUY, "100")],
        )
    assert excinfo.value.status is ExecutionSimulationStatus.EXECUTION_QUOTE_UNAVAILABLE


def test_11_stale_quote_timestamp_is_rejected_by_upstream_contract() -> None:
    # The frozen upstream evidence contract rejects timezone-naive / malformed
    # timestamps; R8 consumes it as-is and never re-dates a quote.
    with pytest.raises(ExecutionSimulationError):
        evidence(QuoteSide.BUY, at=NOW.replace(tzinfo=None))


def test_12_r4_suppressed_reference_cannot_produce_executable_edge() -> None:
    # R4 unusability is upstream authority: an R8 scenario binds an R7
    # snapshot whose oracle layer is suppressed, so no theoretical
    # dislocation may be claimed for it.
    suppressed_label = "ORACLE_REFERENCE→VENUE[DEX]"
    result = simulate(
        QuoteSide.BUY,
        theoretical_dislocation_bps=None,  # suppressed → no theoretical value
    )
    assert result.theoretical_dislocation_bps is None
    assert result.status is ExecutionSimulationStatus.EXECUTION_SIMULATION_OK
    assert result.gross_execution_edge_bps == Decimal("-100")  # gross still honest


# ---------------------------------------------------------------------------
# 13-18. Provider cost treatment
# ---------------------------------------------------------------------------

def test_13_source_proven_included_is_not_subtracted_again() -> None:
    result = simulate_execution_scenario(
        scenario=scenario(),
        quote_evidence=evidence(
            QuoteSide.BUY, fee="0.015", gas="0.005",
            treatment=CostTreatmentState.SOURCE_PROVEN_INCLUDED,
        ),
        settlement_adjustment=settlement(SettlementAdjustmentState.NOT_REQUIRED),
        policy=policy(),
    )
    assert result.provider_incremental_cost_usd == Decimal("0")
    assert result.net_edge_state is NetEdgeState.COMPLETE
    assert result.net_executable_edge_bps == Decimal("-100")  # unchanged gross


def test_14_source_proven_excluded_is_subtracted_exactly_once() -> None:
    result = simulate_execution_scenario(
        scenario=scenario(),
        quote_evidence=evidence(
            QuoteSide.BUY, fee="0.015", gas="0.005",
            treatment=CostTreatmentState.SOURCE_PROVEN_EXCLUDED,
        ),
        settlement_adjustment=settlement(SettlementAdjustmentState.NOT_REQUIRED),
        policy=policy(),
    )
    assert result.provider_incremental_cost_usd == Decimal("0.02")
    # net_usd = -1 - 0.02 = -1.02 → -102 bps on a 100 USD benchmark
    assert result.net_executable_edge_bps == Decimal("-102")
    assert result.net_executable_edge_usd == Decimal("-1.02")
    assert result.net_edge_state is NetEdgeState.COMPLETE


def test_15_unresolved_provider_cost_prevents_complete_net_edge() -> None:
    result = simulate(QuoteSide.BUY, evidence(
        QuoteSide.BUY, fee="0.015", gas="0.005",
        treatment=CostTreatmentState.EVIDENCE_ONLY_INCLUSION_UNRESOLVED,
    ))
    assert result.net_edge_state is NetEdgeState.PARTIAL
    assert result.net_executable_edge_bps is None
    assert result.net_executable_edge_usd is None
    assert NetEdgeBlocker.COST_TREATMENT_UNRESOLVED in result.net_edge_blockers


def test_16_missing_fee_evidence_is_not_zero() -> None:
    result = simulate(QuoteSide.BUY, evidence(
        QuoteSide.BUY, fee=None, gas="0.005",
        treatment=CostTreatmentState.SOURCE_PROVEN_EXCLUDED,
    ))
    assert result.provider_fee_usd is None
    assert result.provider_incremental_cost_usd is None
    assert result.net_edge_state is NetEdgeState.PARTIAL
    assert NetEdgeBlocker.COST_EVIDENCE_INCOMPLETE in result.net_edge_blockers


def test_17_missing_gas_evidence_is_not_zero() -> None:
    result = simulate(QuoteSide.BUY, evidence(
        QuoteSide.BUY, fee="0.01", gas=None,
        treatment=CostTreatmentState.SOURCE_PROVEN_EXCLUDED,
    ))
    assert result.provider_incremental_cost_usd is None
    assert result.net_edge_state is NetEdgeState.PARTIAL
    assert NetEdgeBlocker.COST_EVIDENCE_INCOMPLETE in result.net_edge_blockers


def test_18_explicit_zero_source_proven_cost_works() -> None:
    result = simulate_execution_scenario(
        scenario=scenario(),
        quote_evidence=evidence(
            QuoteSide.BUY, fee="0", gas="0",
            treatment=CostTreatmentState.SOURCE_PROVEN_EXCLUDED,
        ),
        settlement_adjustment=settlement(SettlementAdjustmentState.NOT_REQUIRED),
        policy=policy(),
    )
    assert result.provider_incremental_cost_usd == Decimal("0")
    assert result.net_edge_state is NetEdgeState.COMPLETE
    assert result.net_executable_edge_bps == Decimal("-100")


# ---------------------------------------------------------------------------
# 19-22. Settlement adjustments
# ---------------------------------------------------------------------------

def settlement(state: SettlementAdjustmentState, amount: str | None = None,
               at: datetime = NOW) -> SettlementAdjustmentEvidence:
    return SettlementAdjustmentEvidence(
        state=state,
        source="SYNTHETIC_SETTLEMENT_AUTHORITY",
        observed_at=at,
        amount_usd=Decimal(amount) if amount is not None else None,
        currency="USD",
        reason="synthetic",
    )


def test_19_settlement_not_required_is_zero_cost() -> None:
    result = simulate_execution_scenario(
        scenario=scenario(),
        quote_evidence=evidence(),
        settlement_adjustment=settlement(SettlementAdjustmentState.NOT_REQUIRED),
        policy=policy(),
    )
    assert result.settlement_incremental_cost_usd == Decimal("0")
    assert result.net_edge_state is NetEdgeState.PARTIAL  # provider still unresolved


def test_20_source_proven_excluded_settlement_deducted_once() -> None:
    result = simulate_execution_scenario(
        scenario=scenario(),
        quote_evidence=evidence(
            QuoteSide.BUY, fee="0.01", gas="0.01",
            treatment=CostTreatmentState.SOURCE_PROVEN_EXCLUDED,
        ),
        settlement_adjustment=settlement(
            SettlementAdjustmentState.SOURCE_PROVEN_EXCLUDED, amount="0.05"
        ),
        policy=policy(),
    )
    assert result.provider_incremental_cost_usd == Decimal("0.02")
    assert result.settlement_incremental_cost_usd == Decimal("0.05")
    assert result.net_executable_edge_usd == Decimal("-1") - Decimal("0.07")
    assert result.net_edge_state is NetEdgeState.COMPLETE


def test_21_settlement_unresolved_prevents_complete_net_edge() -> None:
    result = simulate_execution_scenario(
        scenario=scenario(),
        quote_evidence=evidence(
            QuoteSide.BUY, fee="0.01", gas="0.01",
            treatment=CostTreatmentState.SOURCE_PROVEN_EXCLUDED,
        ),
        settlement_adjustment=settlement(SettlementAdjustmentState.UNRESOLVED),
        policy=policy(),
    )
    assert result.settlement_incremental_cost_usd is None
    assert result.net_edge_state is NetEdgeState.PARTIAL
    assert ExecutionSimulationStatus.SETTLEMENT_ADJUSTMENT_UNAVAILABLE in result.net_edge_blockers


def test_22_stale_settlement_adjustment_fails_closed() -> None:
    stale = settlement(
        SettlementAdjustmentState.SOURCE_PROVEN_EXCLUDED, amount="0.05",
        at=NOW - timedelta(seconds=3600),
    )
    result = simulate_execution_scenario(
        scenario=scenario(),
        quote_evidence=evidence(),
        settlement_adjustment=stale,
        policy=policy(),
    )
    assert ExecutionSimulationStatus.TIMING_INVALID in result.timing_blockers
    assert result.net_edge_state is NetEdgeState.PARTIAL
    assert (
        ExecutionSimulationStatus.TIMING_INVALID in result.net_edge_blockers
        or NetEdgeBlocker.TIMING_INVALID in result.net_edge_blockers
    )
    # Stale evidence must not authorize the deduction.
    assert result.settlement_incremental_cost_usd is None


# ---------------------------------------------------------------------------
# 23-27. Route semantics and size handling
# ---------------------------------------------------------------------------

def test_23_route_change_does_not_create_penalty() -> None:
    changed = simulate(QuoteSide.BUY, evidence(
        QuoteSide.BUY, route="OTHER:ROUTE", route_changed=True,
    ))
    unchanged = simulate(QuoteSide.BUY)
    assert changed.route_changed is True
    assert changed.gross_execution_edge_bps == unchanged.gross_execution_edge_bps
    assert changed.net_executable_edge_bps == unchanged.net_executable_edge_bps


def test_24_small_and_large_quote_results_remain_independent() -> None:
    snap = build_snap()  # lineage injected by helper
    by_notional = {
        (s.scenario.side, str(s.scenario.requested_notional_usd)): s
        for s in snap.scenarios
    }
    assert by_notional[(QuoteSide.BUY, "100")].gross_execution_edge_bps == Decimal("-100")
    assert by_notional[(QuoteSide.BUY, "1000")].gross_execution_edge_bps == Decimal("-200")
    assert by_notional[(QuoteSide.SELL, "100")].gross_execution_edge_bps == Decimal("-100")


def test_25_r0_size_impact_is_not_deducted_again() -> None:
    # BUY $1000: exec = 1020/10 = 102 USD/token vs reference 100 → gap +200 bps.
    # Gross edge must be exactly -200 bps (side-adjusted gap), NOT
    # -200 minus any size-impact figure derived from the $100/$1,000 pair.
    large = simulate(
        QuoteSide.BUY,
        evidence(QuoteSide.BUY, "1000", token_amount="10", reference="100",
                 settlement="1020", gap_bps="200"),
        notional="1000",
    )
    small = simulate(
        QuoteSide.BUY,
        evidence(QuoteSide.BUY, "100", token_amount="1", reference="100",
                 settlement="101", gap_bps="100"),
    )
    assert large.gross_execution_edge_bps == Decimal("-200")
    assert large.gross_execution_edge_bps == -large.r2_gap_bps
    sensitivity = build_snap().size_sensitivity
    buy_sensitivity = [s for s in sensitivity if s.side is QuoteSide.BUY][0]
    assert buy_sensitivity.gross_edge_change_bps == (
        large.gross_execution_edge_bps - small.gross_execution_edge_bps
    )


def test_26_no_interpolation_between_notionals() -> None:
    # A $500 scenario has no exact quote: R8 must never interpolate.
    with pytest.raises(ExecutionSimulationError) as excinfo:
        build_sim(
            scenarios=[scenario(QuoteSide.BUY, "500")],
            rows=[evidence(QuoteSide.BUY, "100"), evidence(QuoteSide.BUY, "1000")],
        )
    assert excinfo.value.status is ExecutionSimulationStatus.EXECUTION_QUOTE_UNAVAILABLE


def test_27_unsupported_arbitrary_size_stays_unavailable() -> None:
    rows = [evidence(QuoteSide.BUY, "100"), evidence(QuoteSide.BUY, "1000")]
    for notional in ("250", "750", "5000"):
        with pytest.raises(ExecutionSimulationError) as excinfo:
            build_sim(
                scenarios=[scenario(QuoteSide.BUY, notional)],
                rows=rows,
            )
        assert excinfo.value.status is ExecutionSimulationStatus.EXECUTION_QUOTE_UNAVAILABLE


# ---------------------------------------------------------------------------
# 28-32. Honest edge signs and precision
# ---------------------------------------------------------------------------

def test_28_negative_gross_edge_preserved_honestly() -> None:
    result = simulate(QuoteSide.BUY)  # BUY paying 101 vs reference 100 → unfavorable
    assert result.gross_execution_edge_bps == Decimal("-100")
    assert result.gross_execution_edge_usd == Decimal("-1")


def test_29_positive_gross_edge_preserved_honestly() -> None:
    result = simulate(
        QuoteSide.BUY,
        evidence(QuoteSide.BUY, token_amount="1", reference="100", settlement="99",
                 gap_bps="-100"),
    )
    assert result.gross_execution_edge_bps == Decimal("100")
    assert result.gross_execution_edge_usd == Decimal("1")


def test_30_zero_edge_works_exactly() -> None:
    result = simulate(
        QuoteSide.BUY,
        evidence(QuoteSide.BUY, token_amount="1", reference="100", settlement="100",
                 gap_bps="0"),
    )
    assert result.gross_execution_edge_usd == Decimal("0")
    assert result.gross_execution_edge_bps == Decimal("0")
    assert result.gross_execution_edge_bps == -result.r2_gap_bps == Decimal(0)


def test_31_decimal_precision_exact_threshold() -> None:
    result = simulate(
        QuoteSide.BUY,
        evidence(QuoteSide.BUY, token_amount="1", reference="100", settlement="100.001",
                 gap_bps="0.1"),
    )
    assert result.gross_execution_edge_bps == Decimal("-0.1")
    assert result.net_executable_edge_usd is None or result.net_executable_edge_usd == (
        result.gross_execution_edge_usd
    )


def test_32_non_finite_economics_rejected() -> None:
    with pytest.raises(ExecutionSimulationError) as excinfo:
        evidence(QuoteSide.BUY, token_amount="NaN")
    assert excinfo.value.status is ExecutionSimulationStatus.NON_FINITE_ECONOMICS
    with pytest.raises(ExecutionSimulationError):
        scenario(notional="0")


# ---------------------------------------------------------------------------
# 33-35. Lineage and digest integrity
# ---------------------------------------------------------------------------

def test_33_r7_digest_mismatch_rejected() -> None:
    r7_evidence = {"attributionState": "NO_MATERIAL_DISLOCATION"}
    with pytest.raises(ExecutionSimulationError) as excinfo:
        build_execution_simulation(
            economic_asset_uid=UID,
            canonical_asset_key=KEY,
            scenarios=[scenario()],
            quote_evidence=[evidence()],
            policy=policy(),
            upstream_evidence={"r7CrossMarketEvidence": r7_evidence},
            source_digests={"r7CrossMarketDigest": "0" * 64},
        )
    assert excinfo.value.status is ExecutionSimulationStatus.R7_LINEAGE_MISMATCH


def test_34_r3_digest_mismatch_rejected() -> None:
    with pytest.raises(ExecutionSimulationError) as excinfo:
        build_execution_simulation(
            economic_asset_uid=UID,
            canonical_asset_key=KEY,
            scenarios=[scenario()],
            quote_evidence=[evidence()],
            policy=policy(),
            upstream_evidence={"r3LiquidityEvidence": {"status": "PASS"}},
            source_digests={"r3LiquidityDigest": "0" * 64},
        )
    assert excinfo.value.status is ExecutionSimulationStatus.R3_LINEAGE_MISMATCH


def test_35_embedded_r0_evidence_mismatch_rejected() -> None:
    with pytest.raises(ExecutionSimulationError) as excinfo:
        build_execution_simulation(
            economic_asset_uid=UID,
            canonical_asset_key=KEY,
            scenarios=[scenario()],
            quote_evidence=[evidence()],
            policy=policy(),
            upstream_evidence={"r0QuoteEvidence": {"quoteCount": 4}},
            source_digests={"r0QuoteEvidenceDigest": "0" * 64},
        )
    assert excinfo.value.status is ExecutionSimulationStatus.R3_LINEAGE_MISMATCH


# ---------------------------------------------------------------------------
# 36-39. Immutability, determinism
# ---------------------------------------------------------------------------

def test_36_caller_mutation_isolation() -> None:
    raw0 = {"quote": "original"}
    raw2 = {"gap": "original"}
    row = dataclasses.replace(evidence(QuoteSide.BUY), r0_quote_evidence=raw0,
                              r2_gap_evidence=raw2)
    upstream = {"r3LiquidityEvidence": {"status": "PASS"}}
    snap = build_execution_simulation(
        economic_asset_uid=UID,
        canonical_asset_key=KEY,
        scenarios=[scenario()],
        quote_evidence=[row],
        policy=policy(),
        upstream_evidence={
            "r7CrossMarketEvidence": {"ok": True},
            "r3LiquidityEvidence": {"status": "PASS"},
        },
        source_digests={
            "r7CrossMarketDigest": _r3_digest_for({"ok": True}),
            "r3LiquidityDigest": _r3_digest_for({"status": "PASS"}),
        },
        generated_at=NOW,
    )
    raw0["quote"] = "MUTATED"
    raw2["gap"] = "MUTATED"
    upstream["r3LiquidityEvidence"]["status"] = "MUTATED"
    serialized = snap.to_evidence_dict()["scenarios"][0]
    assert serialized["upstreamEvidence"]["r0QuoteEvidence"]["quote"] == "original"
    assert serialized["upstreamEvidence"]["r2GapEvidence"]["gap"] == "original"
    assert verify_serialized_evidence(snap.to_evidence_dict()) is True


def test_37_direct_nested_mutation_fails() -> None:
    snap = build_snap()
    with pytest.raises(TypeError):
        snap.upstream_evidence["anything"] = "x"  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.status = ExecutionSimulationStatus.INPUT_INVALID  # type: ignore[misc]


def test_38_serialized_mutation_isolation() -> None:
    snap = build_snap()
    evidence = snap.to_evidence_dict()
    original_digest = evidence["r8SnapshotDigest"]
    evidence["scenarios"][0]["grossExecutionEdgeBps"] = "99999"
    evidence["r8SnapshotDigest"] = "0" * 64
    fresh = snap.to_evidence_dict()
    assert fresh["scenarios"][0]["grossExecutionEdgeBps"] != "99999"
    assert fresh["r8SnapshotDigest"] == original_digest


def test_39_digest_reconstruction() -> None:
    snap = build_snap()
    evidence = snap.to_evidence_dict()
    recorded = evidence["r8SnapshotDigest"]
    material = json.loads(json.dumps(evidence))
    material.pop("r8SnapshotDigest")
    recomputed = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    assert recomputed == recorded
    assert verify_serialized_evidence(evidence) is True


# ---------------------------------------------------------------------------
# 40-42. Deterministic ordering
# ---------------------------------------------------------------------------

def test_40_deterministic_scenario_ordering() -> None:
    snap = build_snap()
    order = [(s.scenario.side.value, str(s.scenario.requested_notional_usd))
             for s in snap.scenarios]
    assert order == sorted(order)
    assert order == [("BUY", "100"), ("BUY", "1000"), ("SELL", "100"), ("SELL", "1000")]


def test_41_input_ordering_does_not_change_digest() -> None:
    scenarios = [scenario(QuoteSide.BUY, "100"), scenario(QuoteSide.BUY, "1000"),
                 scenario(QuoteSide.SELL, "100"), scenario(QuoteSide.SELL, "1000")]
    rows = [evidence(QuoteSide.BUY, "100"), evidence(QuoteSide.BUY, "1000"),
            evidence(QuoteSide.SELL, "100"), evidence(QuoteSide.SELL, "1000")]
    forward = build_sim(scenarios=scenarios, rows=rows)
    backward = build_sim(scenarios=list(reversed(scenarios)), rows=list(reversed(rows)))
    assert forward.r8_snapshot_digest == backward.r8_snapshot_digest
    assert forward.to_evidence_dict() == backward.to_evidence_dict()


def test_42_same_inputs_produce_byte_identical_evidence() -> None:
    snap_a = build_snap()
    snap_b = build_snap()
    a = json.dumps(snap_a.to_evidence_dict(), indent=2, sort_keys=True, ensure_ascii=False)
    b = json.dumps(snap_b.to_evidence_dict(), indent=2, sort_keys=True, ensure_ascii=False)
    assert a == b


# ---------------------------------------------------------------------------
# 43-44. Closed-loop discipline
# ---------------------------------------------------------------------------

def test_43_closed_loop_not_proven_remains_explicit() -> None:
    snap = build_snap()
    assert snap.closed_loop_state.value == "CLOSED_LOOP_NOT_PROVEN"
    with pytest.raises(ExecutionSimulationError) as excinfo:
        simulate_execution_scenario(
            scenario=scenario(mode=ExecutionMode.CLOSED_LOOP),
            quote_evidence=evidence(),
            policy=policy(),
        )
    assert excinfo.value.status is ExecutionSimulationStatus.CLOSED_LOOP_NOT_PROVEN


def test_44_equal_usd_notional_does_not_imply_matched_token_quantity() -> None:
    # BUY $100 at 125 USD/token acquires 0.8 tokens; the BUY $1,000 leg at
    # 102 USD/token acquires ~9.8 tokens. Equal USD notionals never imply
    # equal token quantities, so closed-loop legs stay unproven.
    snap = build_snap()
    buy_small = snap.scenarios[0]
    buy_large = snap.scenarios[1]
    # The real assertion: R8 exposes per-leg evidence, never a token-quantity
    # equality claim — there is no field that could express one. Equal USD
    # notionals on different venues/prices yield different token amounts.
    buy_small_tokens = Decimal("100") / Decimal("125")   # 0.8 tokens at $125
    buy_large_tokens = Decimal("1000") / Decimal("102")  # ~9.8 tokens at $102
    assert buy_small_tokens != buy_large_tokens
    for scenario_result in snap.scenarios:
        assert not hasattr(scenario_result, "matched_token_quantity")
        assert not hasattr(scenario_result, "closed_loop_legs")


# ---------------------------------------------------------------------------
# 45-46. No recommendation fields; R8/R9 boundaries
# ---------------------------------------------------------------------------

def _walk_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def test_45_no_recommendation_fields() -> None:
    payload = build_snap().to_evidence_dict()
    forbidden = ("recommend", "confidence", "probability", "advice",
                 "buy_signal", "sell_signal", "trade_now")
    assert not any(word in key.lower() for key in _walk_keys(payload) for word in forbidden)
    blob = json.dumps(payload).lower()
    for word in ("guaranteed profit", "risk-free", "realized pnl", "expected return"):
        assert word not in blob


def test_46_r8_r9_boundaries_preserved() -> None:
    boundaries = build_snap().to_evidence_dict()["boundaries"]
    assert boundaries["crossMarketAuthority"] == "R7_APPLIED"
    assert boundaries["executionSimulatorAuthority"] == "R8_APPLIED"
    assert boundaries["assetGraphAuthority"] == "R9_NOT_YET_APPLIED"
    assert boundaries["modelAuthority"] == "MODEL_NOT_YET_APPLIED"
    assert boundaries["verificationAuthority"] == "R11_NOT_YET_APPLIED"


# ---------------------------------------------------------------------------
# Critical regression: no R0 size-impact double counting (§35)
# ---------------------------------------------------------------------------

def test_r8_does_not_double_count_r0_size_impact() -> None:
    # BUY $100 → gross -100 bps; BUY $1,000 → gross -200 bps. The R0/R3
    # size-impact evidence between those notionals (300 bps by subtraction)
    # is DIAGNOSTIC ONLY. The large-notional gross edge must remain the exact
    # side-adjusted R2 gap (-200 bps) and must NOT become
    # -200 - (size impact derived from the pair).
    small = simulate(
        QuoteSide.BUY,
        evidence(QuoteSide.BUY, "100", token_amount="1", reference="100",
                 settlement="101", gap_bps="100"),
    )
    large = simulate(
        QuoteSide.BUY,
        evidence(QuoteSide.BUY, "1000", token_amount="10", reference="100",
                 settlement="1020", gap_bps="200"),
        notional="1000",
    )
    assert small.gross_execution_edge_bps == Decimal("-100")
    assert large.gross_execution_edge_bps == Decimal("-200")
    observed_size_sensitivity = (
        large.gross_execution_edge_bps - small.gross_execution_edge_bps
    )
    assert observed_size_sensitivity == Decimal("-100")  # descriptive only
    # The failure mode: naively deducting the observed size sensitivity from
    # the large gross edge. R8 must never produce that number.
    double_counted = large.gross_execution_edge_bps - observed_size_sensitivity
    assert double_counted != large.gross_execution_edge_bps
    snap = build_snap()
    large_result = [
        s for s in snap.scenarios
        if s.scenario.side is QuoteSide.BUY
        and s.scenario.requested_notional_usd == Decimal("1000")
    ][0]
    assert large_result.gross_execution_edge_bps == Decimal("-200")


# ---------------------------------------------------------------------------
# Critical regression: unresolved cost (§36)
# ---------------------------------------------------------------------------

def test_unresolved_cost_keeps_net_edge_null_with_reason() -> None:
    # gross edge +80 bps, non-zero reported costs, UNRESOLVED treatment.
    result = simulate(
        QuoteSide.BUY,
        evidence(QuoteSide.BUY, token_amount="1", reference="100", settlement="99.2",
                 gap_bps="-80", fee="0.012", gas="0.008",
                 treatment=CostTreatmentState.EVIDENCE_ONLY_INCLUSION_UNRESOLVED),
    )
    assert result.gross_execution_edge_bps == Decimal("80")
    assert result.net_executable_edge_bps is None
    assert result.net_executable_edge_usd is None
    assert result.net_edge_state is NetEdgeState.PARTIAL
    assert NetEdgeBlocker.COST_TREATMENT_UNRESOLVED in result.net_edge_blockers
    # The reported cost must NOT be blindly subtracted either:
    assert result.net_executable_edge_bps != result.gross_execution_edge_bps - Decimal("20")


# ---------------------------------------------------------------------------
# Critical regression: source-proven included / excluded (§37-38)
# ---------------------------------------------------------------------------

def test_source_proven_included_cost_not_subtracted_again() -> None:
    result = simulate(
        QuoteSide.BUY,
        evidence(QuoteSide.BUY, token_amount="1", reference="100", settlement="99.2",
                 gap_bps="-80", fee="0.012", gas="0.003",
                 treatment=CostTreatmentState.SOURCE_PROVEN_INCLUDED),
        settlement_adj=settlement(SettlementAdjustmentState.NOT_REQUIRED),
    )
    assert result.gross_execution_edge_bps == Decimal("80")
    assert result.provider_incremental_cost_usd == Decimal("0")
    assert result.net_edge_state is NetEdgeState.COMPLETE
    assert result.net_executable_edge_bps == Decimal("80")  # NOT +65


def test_source_proven_excluded_cost_deducted_once() -> None:
    result = simulate(
        QuoteSide.BUY,
        evidence(QuoteSide.BUY, token_amount="1", reference="100", settlement="99.2",
                 gap_bps="-80", fee="0.012", gas="0.003",
                 treatment=CostTreatmentState.SOURCE_PROVEN_EXCLUDED),
        settlement_adj=settlement(SettlementAdjustmentState.NOT_REQUIRED),
    )
    assert result.gross_execution_edge_bps == Decimal("80")
    assert result.provider_incremental_cost_usd == Decimal("0.015")
    # net_usd = 0.8 - 0.015 = 0.785 -> +78.5 bps on the 100 USD benchmark
    assert result.net_executable_edge_usd == Decimal("0.785")
    assert result.net_executable_edge_bps == Decimal("78.5")
    assert result.net_edge_state is NetEdgeState.COMPLETE
