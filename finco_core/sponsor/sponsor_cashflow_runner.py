"""Phase 7A — Sponsor cashflow runner.

Pure-function sponsor cashflow computation from HoldCo results and equity injections.
Deterministic. Immutable. Audit-safe.
"""
from __future__ import annotations

import math
from typing import Any

from finco_core.sponsor.equity_injection import EquityInjection
from finco_core.sponsor.sponsor_cashflow_result import (
    SponsorCashflowPeriodResult,
    SponsorCashflowResult,
)
from finco_core.sponsor.sponsor_capital_account import (
    CapitalAccountEntry,
    SponsorCapitalAccount,
)

__all__ = [
    "SponsorCashflowRunnerInputs",
    "run_sponsor_cashflows",
]


# ── Runner inputs ─────────────────────────────────────────────────────────────
from dataclasses import dataclass


@dataclass(frozen=True)
class SponsorCashflowRunnerInputs:
    """Inputs for the sponsor cashflow runner.

    Immutable. All mutable collections normalized to tuples on construction.

    Attributes
    ----------
    investor_id : str
        Sponsor/investor identifier.
    entity_code : str
        Target entity code (e.g., "HOLDCO", "PORTFOLIO").
    equity_injections : tuple[EquityInjection, ...]
        Immutable tuple of equity injection events.
    holdco_distribution_by_period : tuple[float, ...]
        Distribution from HoldCo to sponsor per period (kEUR).
        Length must equal period_count.
        IGNORED when distribution_account_received_by_period is provided.
    distribution_account_received_by_period : tuple[float, ...] | None, optional
        Explicit distribution cashflow from DistributionAccount per period (kEUR).
        When provided (non-None), overrides holdco_distribution_by_period for this period.
        Default None means use holdco_distribution_by_period (existing behavior).
        Length must equal period_count.
    holdco_dividend_by_period : tuple[float, ...]
        Dividend component of distribution per period (kEUR).
        Used for WHT calculation basis. Length must match
        holdco_distribution_by_period.
    wht_rate : float
        Withholding tax rate applied to distributions (0.0 to 1.0).
        Must be >= 0 and <= 1.
    holdco_opex_by_period : tuple[float, ...]
        HoldCo operating expenses per period (kEUR). Included for
        audit reference but not deducted at sponsor level.
    period_count : int
        Number of semiannual periods to model.
    metadata : tuple[tuple[str, Any], ...], optional
        Key-value metadata as frozen tuple of (key, value) 2-tuples.
        Values must be JSON-serializable immutables: str, int, float, bool, None.
    notes : tuple[str, ...], optional
        Top-level audit notes.
    """
    investor_id: str
    entity_code: str
    equity_injections: tuple[EquityInjection, ...]
    holdco_distribution_by_period: tuple[float, ...]
    holdco_dividend_by_period: tuple[float, ...]
    wht_rate: float
    holdco_opex_by_period: tuple[float, ...]
    period_count: int
    distribution_account_received_by_period: tuple[float, ...] | None = None
    metadata: tuple[tuple[str, Any], ...] = ()
    notes: tuple[str, ...] = ()

    _IMMUTABLE_JSON_SCALARS = (str, int, float, bool, type(None))

    def __post_init__(self):
        # Normalize equity_injections to tuple
        if not isinstance(self.equity_injections, tuple):
            object.__setattr__(self, "equity_injections", tuple(self.equity_injections))
        # Normalize holdco_distribution_by_period to tuple
        if not isinstance(self.holdco_distribution_by_period, tuple):
            object.__setattr__(self, "holdco_distribution_by_period", tuple(self.holdco_distribution_by_period))
        # Normalize holdco_dividend_by_period to tuple
        if not isinstance(self.holdco_dividend_by_period, tuple):
            object.__setattr__(self, "holdco_dividend_by_period", tuple(self.holdco_dividend_by_period))
        # Normalize holdco_opex_by_period to tuple
        if not isinstance(self.holdco_opex_by_period, tuple):
            object.__setattr__(self, "holdco_opex_by_period", tuple(self.holdco_opex_by_period))
        # Normalize metadata to sorted frozen tuple
        if isinstance(self.metadata, dict):
            items = tuple(sorted((str(k), _normalize_metadata_val(v)) for k, v in self.metadata.items()))
            object.__setattr__(self, "metadata", items)
        elif not isinstance(self.metadata, tuple):
            object.__setattr__(self, "metadata", tuple(self.metadata))
        else:
            # Validate and re-freeze
            normalized = tuple(sorted((str(k), _normalize_metadata_val(v)) for k, v in self.metadata))
            object.__setattr__(self, "metadata", normalized)
        # Normalize notes to tuple
        if not isinstance(self.notes, tuple):
            object.__setattr__(self, "notes", tuple(str(n) for n in (
                self.notes if isinstance(self.notes, (list, tuple)) else [self.notes]
            )))
        # Normalize distribution_account_received_by_period to tuple when provided
        if self.distribution_account_received_by_period is not None:
            if not isinstance(self.distribution_account_received_by_period, tuple):
                object.__setattr__(self, "distribution_account_received_by_period",
                    tuple(self.distribution_account_received_by_period))
        else:
            object.__setattr__(self, "distribution_account_received_by_period", None)


# ── Metadata normalization ────────────────────────────────────────────────────

_IMMUTABLE_JSON_SCALARS = (str, int, float, bool, type(None))


def _normalize_metadata_val(v: Any) -> Any:
    """Normalize a metadata value to an immutable JSON scalar.

    Rejects dict/list/nested mutable structures. Values must be one of:
    str, int, float, bool, None (or collections of these).

    Raises TypeError if a mutable container is encountered.
    """
    if isinstance(v, _IMMUTABLE_JSON_SCALARS):
        return v
    if isinstance(v, dict):
        raise TypeError(
            f"Metadata dict values not allowed; use flat tuple of (key, value) pairs. "
            f"Got dict with keys: {list(v.keys())}"
        )
    if isinstance(v, list):
        raise TypeError(
            f"Metadata list values not allowed; use tuple of (key, value) pairs. "
            f"Got list: {v!r}"
        )
    if isinstance(v, tuple):
        normalized = tuple(_normalize_metadata_val(x) for x in v)
        # Check that no mutable was returned (would mean nested list/dict)
        for x in normalized:
            if isinstance(x, (list, dict)):
                raise TypeError(
                    f"Metadata tuple must contain only JSON scalars, "
                    f"got nested container {type(x).__name__}"
                )
        return normalized
    raise TypeError(
        f"Metadata value must be a JSON scalar (str, int, float, bool, None), "
        f"got {type(v).__name__}: {v!r}"
    )


# ── Validation helpers ────────────────────────────────────────────────────────

def _validate_series(name: str, values: tuple[float, ...], period_count: int) -> None:
    if len(values) != period_count:
        raise ValueError(
            f"{name}: expected {period_count} periods, got {len(values)}"
        )
    for i, v in enumerate(values):
        if math.isnan(v) or math.isinf(v):
            raise ValueError(f"{name}[{i}] must be finite, got {v}")
        if v < 0.0:
            raise ValueError(f"{name}[{i}] must be >= 0, got {v}")


def _validate_finite(name: str, value: float) -> None:
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"{name} must be finite, got {value}")


# ── Pure-function runner ──────────────────────────────────────────────────────

def run_sponsor_cashflows(
    inputs: SponsorCashflowRunnerInputs,
) -> SponsorCashflowResult:
    """Compute sponsor cashflows from HoldCo results and equity injections.

    This is a pure function — no mutation, no side effects, no hidden state.
    Deterministic: same inputs always produce identical outputs.

    Parameters
    ----------
    inputs : SponsorCashflowRunnerInputs
        All inputs bundled in a dataclass for explicit dependency injection.

    Returns
    -------
    SponsorCashflowResult
        Per-period results with running capital account balance.

    Logic
    -----
    For each period t:
      1. equity_injected[t]  = sum of EquityInjection amounts where period_index == t
      2. distribution[t]    = holdco_distribution_by_period[t]
      3. wht[t]              = distribution[t] * wht_rate
      4. net_cashflow[t]    = distribution[t] - equity_injected[t] - wht[t]
      5. capital_balance[t]  = capital_balance[t-1] + equity_injected[t] - distribution[t]

    capital_account[t] starts at 0 and accumulates equity injections minus distributions.
    When a distribution exceeds accumulated equity injections, capital_balance may decrease
    (net return phase).

    WHT is computed on the gross distribution (before WHT), consistent with the
    HoldCo tax engine's WHT calculation basis.
    """
    # ── Validate inputs ──────────────────────────────────────────────────────
    if not inputs.investor_id.strip():
        raise ValueError("investor_id must be non-empty")
    if not inputs.entity_code.strip():
        raise ValueError("entity_code must be non-empty")
    if inputs.period_count < 0:
        raise ValueError(f"period_count must be >= 0, got {inputs.period_count}")
    if not (0.0 <= inputs.wht_rate <= 1.0):
        raise ValueError(f"wht_rate must be between 0 and 1, got {inputs.wht_rate}")

    _validate_series(
        "holdco_distribution_by_period",
        inputs.holdco_distribution_by_period,
        inputs.period_count,
    )
    _validate_series(
        "holdco_dividend_by_period",
        inputs.holdco_dividend_by_period,
        inputs.period_count,
    )
    _validate_series(
        "holdco_opex_by_period",
        inputs.holdco_opex_by_period,
        inputs.period_count,
    )

    if inputs.distribution_account_received_by_period is not None:
        _validate_series(
            "distribution_account_received_by_period",
            inputs.distribution_account_received_by_period,
            inputs.period_count,
        )

    for inj in inputs.equity_injections:
        if inj.period_index < 0 or inj.period_index >= inputs.period_count:
            raise ValueError(
                f"EquityInjection period_index {inj.period_index} out of range "
                f"[0, {inputs.period_count})"
            )
        _validate_finite("equity_injection amount", inj.amount_keur)

    # ── Build injection lookup ───────────────────────────────────────────────
    injection_by_period: dict[int, float] = {}
    for inj in inputs.equity_injections:
        injection_by_period[inj.period_index] = (
            injection_by_period.get(inj.period_index, 0.0) + inj.amount_keur
        )

    # ── Compute per-period results ──────────────────────────────────────────
    period_results: list[SponsorCashflowPeriodResult] = []
    cap_account_entries: list[CapitalAccountEntry] = []

    capital_balance = 0.0
    total_equity_injected = 0.0
    total_distributions = 0.0
    total_wht = 0.0
    total_net_cashflow = 0.0

    for t in range(inputs.period_count):
        equity_injected = injection_by_period.get(t, 0.0)
        distribution = inputs.holdco_distribution_by_period[t]
        # Override with DistributionAccount handoff when provided
        if inputs.distribution_account_received_by_period is not None:
            distribution = inputs.distribution_account_received_by_period[t]
        dividend_component = inputs.holdco_dividend_by_period[t]
        opex = inputs.holdco_opex_by_period[t]
        wht = distribution * inputs.wht_rate

        net_cashflow = distribution - equity_injected - wht
        capital_balance = capital_balance + equity_injected - distribution

        # Build notes for this period
        notes_parts: list[str] = []
        if equity_injected > 0:
            inj_sources = [
                inj.purpose
                for inj in inputs.equity_injections
                if inj.period_index == t
            ]
            notes_parts.append(f"equity injection: {', '.join(inj_sources)}")
        if distribution > 0:
            notes_parts.append(f"distribution from HoldCo: {distribution:.2f} kEUR")
        if wht > 0:
            notes_parts.append(f"WHT withheld: {wht:.2f} kEUR")
        if capital_balance > 0 and equity_injected == 0 and distribution == 0:
            notes_parts.append("no activity this period")
        notes = tuple(notes_parts) if notes_parts else ("no activity",)

        period_result = SponsorCashflowPeriodResult(
            period_index=t,
            equity_injected_keur=equity_injected,
            distribution_received_keur=distribution,
            wht_on_distribution_keur=wht,
            net_cashflow_keur=net_cashflow,
            capital_account_balance_keur=capital_balance,
            notes=notes,
        )
        period_results.append(period_result)

        # Capital account entries
        if equity_injected > 0:
            for inj in inputs.equity_injections:
                if inj.period_index == t:
                    cap_account_entries.append(
                        CapitalAccountEntry(
                            entry_type="contribution",
                            period_index=t,
                            amount_keur=inj.amount_keur,
                            running_balance_keur=capital_balance,
                            investor_id=inputs.investor_id,
                            source=inj.purpose,
                            notes=(f"equity injection: {inj.purpose}",),
                        )
                    )
        if distribution > 0:
            cap_account_entries.append(
                CapitalAccountEntry(
                    entry_type="distribution",
                    period_index=t,
                    amount_keur=distribution,
                    running_balance_keur=capital_balance,
                    investor_id=inputs.investor_id,
                    source="distribution_from_holdco",
                    notes=(
                        f"distribution (gross={distribution:.2f} kEUR, "
                        f"wht={wht:.2f} kEUR, dividend={dividend_component:.2f} kEUR, "
                        f"opex={opex:.2f} kEUR)",
                    ),
                )
            )

        total_equity_injected += equity_injected
        total_distributions += distribution
        total_wht += wht
        total_net_cashflow += net_cashflow

    # ── Build capital account ───────────────────────────────────────────────
    cap_account = SponsorCapitalAccount(
        investor_id=inputs.investor_id,
        entity_code=inputs.entity_code,
        entries=tuple(cap_account_entries),
        total_contributed_keur=total_equity_injected,
        total_distributions_keur=total_distributions,
        net_contributed_keur=total_equity_injected - total_distributions,
        final_balance_keur=capital_balance,
        metadata=inputs.metadata,
        notes=inputs.notes,
    )

    # ── Build result ─────────────────────────────────────────────────────────
    gross_multiple: float | None = None
    if total_equity_injected > 0:
        gross_multiple = total_distributions / total_equity_injected

    result = SponsorCashflowResult(
        investor_id=inputs.investor_id,
        entity_code=inputs.entity_code,
        period_results=tuple(period_results),
        total_equity_injected_keur=total_equity_injected,
        total_distributions_received_keur=total_distributions,
        total_wht_keur=total_wht,
        total_net_cashflow_keur=total_net_cashflow,
        gross_sponsor_return_multiple=gross_multiple,
        metadata=(
            ("wht_rate", inputs.wht_rate),
            ("period_count", inputs.period_count),
            ("equity_injection_count", len(inputs.equity_injections)),
            ("distribution_count", sum(1 for d in inputs.holdco_distribution_by_period if d > 0)),
            ("run_type", "sponsor_cashflow"),
            ("phase", "7A"),
            *inputs.metadata,
        ),
        notes=(
            "Sponsor cashflow result — Phase 7A foundation.",
            "Net cashflow = distribution - equity_injected - WHT.",
            f"Capital account balance after period {inputs.period_count - 1}: {capital_balance:.2f} kEUR.",
            "IRR not yet computed — Phase 7B topic.",
        ),
    )

    return result
