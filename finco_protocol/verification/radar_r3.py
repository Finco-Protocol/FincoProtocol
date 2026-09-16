"""Independent read-only verification of serialized FINCO Radar R3 evidence."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from finco_radar.liquidity.engine import (
    BUY_SIZE_PAIR,
    CROSS_SIDE_100,
    CROSS_SIDE_1000,
    LARGE_NOTIONAL_USD,
    SELL_SIZE_PAIR,
    SMALL_NOTIONAL_USD,
)


RADAR_R3_VALIDATION_SCHEMA = "finco.radar-r3-validation.v1"
DECIMAL_TOL = Decimal("1e-18")

_EXPECTED_QUOTE_MATRIX: dict[str, tuple[str, Decimal]] = {
    "BUY_100": ("BUY", SMALL_NOTIONAL_USD),
    "BUY_1000": ("BUY", LARGE_NOTIONAL_USD),
    "SELL_100": ("SELL", SMALL_NOTIONAL_USD),
    "SELL_1000": ("SELL", LARGE_NOTIONAL_USD),
}
_EXPECTED_COST_MATRIX = frozenset(_EXPECTED_QUOTE_MATRIX.values())
_EXPECTED_TEMPORAL_PAIRS = frozenset(
    {BUY_SIZE_PAIR, SELL_SIZE_PAIR, CROSS_SIDE_100, CROSS_SIDE_1000}
)


@dataclass(frozen=True)
class RadarInvariantCheck:
    invariant_id: str
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "invariantId": self.invariant_id,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class RadarR3ValidationReport:
    schema: str
    asset_uid: str
    checks: tuple[RadarInvariantCheck, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failures(self) -> tuple[RadarInvariantCheck, ...]:
        return tuple(check for check in self.checks if not check.passed)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "assetUid": self.asset_uid,
            "passed": self.passed,
            "checks": [check.as_dict() for check in self.checks],
        }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _close(left: Any, right: Any, tolerance: Decimal = DECIMAL_TOL) -> bool:
    a = _decimal(left)
    b = _decimal(right)
    return a is not None and b is not None and abs(a - b) <= tolerance


def _check(invariant_id: str, passed: bool, detail: str) -> RadarInvariantCheck:
    return RadarInvariantCheck(invariant_id=invariant_id, passed=bool(passed), detail=detail)


def _walk_mapping_keys(value: Any):
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _walk_mapping_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_mapping_keys(item)


def validate_radar_r3_evidence(evidence: Mapping[str, Any]) -> RadarR3ValidationReport:
    """Validate the published R3 evidence contract without re-routing quotes.

    R3 remains the sole liquidity-measurement authority. This verifier checks
    that serialized evidence preserves the exact structural matrix and identities
    that the R3 authority emitted; it does not request routes or recreate R0-R3.
    """

    checks: list[RadarInvariantCheck] = []
    asset = _mapping(evidence.get("asset"))
    asset_uid = str(asset.get("assetUid") or "")

    checks.append(
        _check(
            "R3_STATUS_LIQUIDITY_OK",
            evidence.get("status") == "LIQUIDITY_OK",
            f"status={evidence.get('status')!r}",
        )
    )
    checks.append(
        _check(
            "R3_CANONICAL_IDENTITY_PRESENT",
            bool(asset_uid) and bool(asset.get("canonicalKey")),
            f"assetUid={asset_uid!r}; canonicalKey={asset.get('canonicalKey')!r}",
        )
    )

    notionals = _mapping(evidence.get("observationNotionals"))
    small = _decimal(notionals.get("smallNotionalUsd"))
    large = _decimal(notionals.get("largeNotionalUsd"))
    notionals_ok = small == SMALL_NOTIONAL_USD and large == LARGE_NOTIONAL_USD
    checks.append(
        _check(
            "R3_NOTIONAL_ORDERING",
            notionals_ok,
            (
                "exact R3 observation notionals are 100 USD and 1000 USD"
                if notionals_ok
                else f"small={small!r}; large={large!r}"
            ),
        )
    )

    quotes = _sequence(evidence.get("quoteMatrixEvidence"))
    seen_quote_slots: set[str] = set()
    quote_matrix_failures: list[str] = []
    for raw_item in quotes:
        item = _mapping(raw_item)
        slot = item.get("slot")
        if not isinstance(slot, str) or slot not in _EXPECTED_QUOTE_MATRIX:
            quote_matrix_failures.append(f"unknown-slot:{slot!r}")
            continue
        if slot in seen_quote_slots:
            quote_matrix_failures.append(f"duplicate-slot:{slot}")
            continue
        seen_quote_slots.add(slot)
        expected_side, expected_notional = _EXPECTED_QUOTE_MATRIX[slot]
        side = item.get("side")
        requested_notional = _decimal(item.get("requestedNotionalUsd"))
        if item.get("status") != "QUOTE_OK":
            quote_matrix_failures.append(f"{slot}:status={item.get('status')!r}")
        if side != expected_side:
            quote_matrix_failures.append(f"{slot}:side={side!r}")
        if requested_notional != expected_notional:
            quote_matrix_failures.append(
                f"{slot}:requestedNotionalUsd={item.get('requestedNotionalUsd')!r}"
            )
    quote_matrix_ok = (
        len(quotes) == 4
        and seen_quote_slots == set(_EXPECTED_QUOTE_MATRIX)
        and not quote_matrix_failures
    )
    checks.append(
        _check(
            "R3_EXACT_QUOTE_MATRIX",
            quote_matrix_ok,
            (
                "exact BUY/SELL x 100/1000 quote matrix with bound side/notional/status"
                if quote_matrix_ok
                else f"failures={quote_matrix_failures!r}; slots={sorted(seen_quote_slots)!r}"
            ),
        )
    )

    gap = _mapping(evidence.get("gapEvidence"))
    buy_100 = _decimal(gap.get("buyGapBpsAt100"))
    buy_1000 = _decimal(gap.get("buyGapBpsAt1000"))
    sell_100 = _decimal(gap.get("sellGapBpsAt100"))
    sell_1000 = _decimal(gap.get("sellGapBpsAt1000"))
    buy_delta = _decimal(gap.get("buyDirectionalGapDeltaBps"))
    sell_delta = _decimal(gap.get("sellDirectionalGapDeltaBps"))
    checks.append(
        _check(
            "R3_BUY_GAP_DELTA_IDENTITY",
            None not in (buy_100, buy_1000, buy_delta)
            and _close(buy_1000 - buy_100, buy_delta),
            "buy directional gap delta = BUY gap @ large - BUY gap @ small",
        )
    )
    checks.append(
        _check(
            "R3_SELL_GAP_DELTA_IDENTITY",
            None not in (sell_100, sell_1000, sell_delta)
            and _close(sell_1000 - sell_100, sell_delta),
            "sell directional gap delta = SELL gap @ large - SELL gap @ small",
        )
    )

    spread = _mapping(evidence.get("spreadEvidence"))
    spread_failures: list[str] = []
    computed_spreads: dict[str, Decimal] = {}
    for label in ("at100", "at1000"):
        row = _mapping(spread.get(label))
        buy = _decimal(row.get("buyExecutionPriceUsdPerToken"))
        sell = _decimal(row.get("sellExecutionPriceUsdPerToken"))
        mid = _decimal(row.get("executionMidPriceUsdPerToken"))
        stated_spread = _decimal(row.get("executionSpreadBps"))
        if None in (buy, sell, mid, stated_spread) or mid <= 0:
            spread_failures.append(label)
            continue
        expected_mid = (buy + sell) / Decimal("2")
        expected_spread = (buy - sell) / expected_mid * Decimal("10000")
        if not (_close(expected_mid, mid) and _close(expected_spread, stated_spread)):
            spread_failures.append(label)
            continue
        computed_spreads[label] = stated_spread
    checks.append(
        _check(
            "R3_EXECUTION_SPREAD_FORMULA",
            not spread_failures and len(computed_spreads) == 2,
            "cross-side spread formula reconciles at both notionals"
            if not spread_failures and len(computed_spreads) == 2
            else f"failures={spread_failures!r}",
        )
    )

    stated_spread_delta = _decimal(spread.get("executionSpreadDeltaBps"))
    spread_delta_ok = (
        "at100" in computed_spreads
        and "at1000" in computed_spreads
        and stated_spread_delta is not None
        and _close(computed_spreads["at1000"] - computed_spreads["at100"], stated_spread_delta)
    )
    checks.append(
        _check(
            "R3_SPREAD_DELTA_IDENTITY",
            spread_delta_ok,
            "spread delta = spread @ large - spread @ small",
        )
    )

    route = _mapping(evidence.get("routeEvidence"))
    route_signatures = (
        _mapping(route.get("buy")).get("smallRouteSignature"),
        _mapping(route.get("buy")).get("largeRouteSignature"),
        _mapping(route.get("sell")).get("smallRouteSignature"),
        _mapping(route.get("sell")).get("largeRouteSignature"),
    )
    route_ok = all(
        isinstance(signature, str)
        and bool(signature)
        and signature != "NO_ROUTE_EVIDENCE"
        for signature in route_signatures
    )
    checks.append(
        _check(
            "R3_ROUTE_EVIDENCE_PRESENT",
            route_ok,
            "all four quote slots carry canonical route evidence",
        )
    )

    costs = _sequence(evidence.get("costEvidence"))
    cost_slots: set[tuple[str, Decimal]] = set()
    cost_failures: list[str] = []
    for index, raw_item in enumerate(costs):
        item = _mapping(raw_item)
        side = item.get("side")
        notional = _decimal(item.get("requestedNotionalUsd"))
        if not isinstance(side, str) or notional is None:
            cost_failures.append(f"row-{index}:malformed")
            continue
        slot = (side, notional)
        if slot in cost_slots:
            cost_failures.append(f"row-{index}:duplicate={slot!r}")
        cost_slots.add(slot)
    costs_ok = (
        len(costs) == 4
        and cost_slots == _EXPECTED_COST_MATRIX
        and not cost_failures
    )
    checks.append(
        _check(
            "R3_COST_EVIDENCE_FOUR_SLOTS",
            costs_ok,
            (
                "cost evidence binds exactly to BUY/SELL x 100/1000 matrix"
                if costs_ok
                else f"slots={sorted((side, str(n)) for side, n in cost_slots)!r}; failures={cost_failures!r}"
            ),
        )
    )

    temporal = _mapping(evidence.get("temporalEvidence"))
    policy = _mapping(temporal.get("policy"))
    max_allowed = _decimal(policy.get("maxQuotePairSkewSeconds"))
    observed = _mapping(temporal.get("observedPairSkews"))
    observed_keys = set(observed.keys())
    observed_values: dict[str, Decimal] = {}
    temporal_failures: list[str] = []
    for label in _EXPECTED_TEMPORAL_PAIRS:
        value = _decimal(observed.get(label))
        if value is None or value < 0:
            temporal_failures.append(f"{label}={observed.get(label)!r}")
            continue
        observed_values[label] = value
    if observed_keys != _EXPECTED_TEMPORAL_PAIRS:
        temporal_failures.append(
            f"pairKeys={sorted(str(key) for key in observed_keys)!r}"
        )
    stated_max = _decimal(temporal.get("maxObservedPairSkewSeconds"))
    temporal_ok = (
        max_allowed is not None
        and max_allowed > 0
        and not temporal_failures
        and len(observed_values) == 4
        and stated_max is not None
        and stated_max >= 0
        and _close(max(observed_values.values()), stated_max)
        and stated_max <= max_allowed
    )
    checks.append(
        _check(
            "R3_TEMPORAL_COHERENCE",
            temporal_ok,
            (
                f"observedMax={stated_max!r}; allowed={max_allowed!r}; canonicalPairs=4"
                if temporal_ok
                else f"observedMax={stated_max!r}; allowed={max_allowed!r}; failures={temporal_failures!r}"
            ),
        )
    )

    lineage = _mapping(evidence.get("lineage"))
    lineage_ok = all(
        bool(lineage.get(name))
        for name in (
            "r0FormulaAuthority",
            "r2ObservationAuthority",
            "r1CanonicalIdentity",
            "quoteSource",
            "gitHead",
            "producedAt",
        )
    )
    checks.append(
        _check(
            "R3_LINEAGE_COMPLETE",
            lineage_ok,
            "R0/R1/R2 authority, quote source, git head and production time are present",
        )
    )

    boundaries = _mapping(evidence.get("boundaries"))
    boundaries_ok = (
        boundaries.get("referenceStateAuthority") == "R4_NOT_YET_APPLIED"
        and boundaries.get("signalAuthority") == "R5_NOT_YET_APPLIED"
        and boundaries.get("terminalAuthority") == "R6_NOT_YET_APPLIED"
    )
    checks.append(
        _check(
            "R3_BOUNDARIES_PRESERVED",
            boundaries_ok,
            f"boundaries={dict(boundaries)!r}",
        )
    )

    prohibited_exact_keys = {
        "score",
        "liquidityScore",
        "classification",
        "tradeSignal",
        "tradingSignal",
        "recommendation",
    }
    present_prohibited = sorted(
        {key for key in _walk_mapping_keys(evidence) if key in prohibited_exact_keys}
    )
    checks.append(
        _check(
            "R3_NO_SCORE_OR_SIGNAL",
            not present_prohibited,
            "no composite score/classification/trading signal"
            if not present_prohibited
            else f"prohibitedKeys={present_prohibited!r}",
        )
    )

    return RadarR3ValidationReport(
        schema=RADAR_R3_VALIDATION_SCHEMA,
        asset_uid=asset_uid,
        checks=tuple(checks),
    )


def build_radar_r3_validation_claim(
    evidence: Mapping[str, Any],
    report: RadarR3ValidationReport | None = None,
) -> dict[str, Any]:
    """Bundle complete reconstructible R3 evidence with its validation report."""

    resolved_report = report or validate_radar_r3_evidence(evidence)
    return {
        "schema": RADAR_R3_VALIDATION_SCHEMA,
        "validation": resolved_report.as_dict(),
        "r3Evidence": dict(evidence),
    }
