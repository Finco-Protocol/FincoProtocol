"""app.v2.developer_economics_projection — Developer Economics workspace (presentation only).

Projects the EXISTING Developer Economics V1 authority for display.  There is no
second calculator here: every figure on an ACTIVE workspace is read from
``financial_engine.developer_economics.compute_developer_economics`` /
``resolve_developer_project_uses`` applied to the effective typed
``ProjectInputs.development_economics``.  Nothing is derived, defaulted or
"improved" in this module; unavailable stays unavailable (never zero).

States
------
DISABLED   ``development_economics`` is absent or ``enabled=False``.  The capability is
           a neutral no-op; the Run is byte-identical to the reference.  No figure is
           shown and none is invented.
ACTIVE     enabled and valid -> sections A-E carry canonical figures.
INVALID    enabled but the canonical calculator fails closed (e.g. spend after
           Financial Close) -> the typed error is shown, no figure.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

NA = "—"

STATE_DISABLED = "DISABLED"
STATE_ACTIVE = "ACTIVE"
STATE_INVALID = "INVALID"

_STATUS_REASON = {
    "NO_NEGATIVE_CASHFLOW": "No development spend — there is no developer outflow to measure a return against.",
    "NO_POSITIVE_CASHFLOW": "No reimbursement or fee — the developer receives nothing, so no IRR exists.",
    "NON_CONVERGENT": "The XIRR solver did not converge on the dated developer vector.",
    "ZERO_CONTRIBUTION": "Development spend is zero — MOIC has no denominator authority.",
}


def _keur(value: Optional[float]) -> str:
    if value is None:
        return NA
    return f"{value:,.1f}"


def _pct(value: Optional[float], digits: int = 2) -> str:
    return NA if value is None else f"{value * 100:.{digits}f}%"


def _multiple(value: Optional[float]) -> str:
    return NA if value is None else f"{value:.2f}x"


@dataclass(frozen=True)
class SpendRow:
    spend_date: str
    amount: str


@dataclass(frozen=True)
class VectorRow:
    cashflow_date: str
    spend: str
    reimbursement: str
    fee: str
    net: str


@dataclass(frozen=True)
class DeveloperMetric:
    key: str
    label: str
    display: str
    available: bool
    reason: str = ""      # typed unavailable reason


@dataclass(frozen=True)
class DeveloperWorkspace:
    state: str                                   # DISABLED | ACTIVE | INVALID
    state_note: str
    outcome: str = ""
    settlement_date: str = ""
    spend_rows: tuple[SpendRow, ...] = ()
    total_spend: str = NA
    reimbursement: str = NA
    reimbursement_note: str = ""
    fee_mode: str = ""
    fee_input_display: str = ""                  # "5.00% of hard CAPEX" | "400.0 kEUR"
    fee_amount: str = NA
    fee_basis: str = ""
    fee_basis_authority: str = ""
    total_receipts: str = NA
    metrics: tuple[DeveloperMetric, ...] = ()
    vector: tuple[VectorRow, ...] = ()
    project_uses_total: str = NA                 # section E: developer uses added to project uses
    uses_lines: tuple[tuple[str, str], ...] = ()
    error_code: str = ""
    error_detail: str = ""

    @property
    def is_active(self) -> bool:
        return self.state == STATE_ACTIVE


def _fee_input_display(config: Any) -> str:
    mode = config.developer_fee_mode.value
    if mode == "PCT_OF_HARD_CAPEX":
        # 0.05 is 5.00 % — the stored fraction is never shown as "0.05%".
        return f"{config.developer_fee_value * 100:.2f}% of hard CAPEX"
    return f"{_keur(config.developer_fee_value)} kEUR fixed"


def build_developer_workspace(project_inputs: Any) -> DeveloperWorkspace:
    """Project the developer workspace from the effective typed ProjectInputs."""
    config = getattr(project_inputs, "development_economics", None)
    if config is None or not getattr(config, "enabled", False):
        return DeveloperWorkspace(
            state=STATE_DISABLED,
            state_note=(
                "Developer Economics is not enabled for this project. The capability is a neutral "
                "no-op: Sources & Uses, returns and exports equal the reference economics exactly."
            ),
        )

    from financial_engine.developer_economics import (
        compute_developer_economics,
        resolve_developer_project_uses,
    )

    try:
        result = compute_developer_economics(project_inputs)
        uses = resolve_developer_project_uses(project_inputs)
    except ValueError as exc:
        text = str(exc)
        code, _, detail = text.partition(":")
        return DeveloperWorkspace(
            state=STATE_INVALID,
            state_note="The canonical Developer Economics calculator rejected the typed input; no figure is shown.",
            error_code=code.strip(), error_detail=detail.strip(),
        )
    if result is None:
        return DeveloperWorkspace(state=STATE_DISABLED, state_note="Developer Economics is inactive.")

    spend_rows = tuple(
        SpendRow(spend_date=e.spend_date.isoformat(), amount=_keur(e.amount_keur))
        for e in config.spend_schedule
    )
    vector = tuple(
        VectorRow(
            cashflow_date=r.cashflow_date.isoformat(),
            spend=_keur(-r.development_spend_keur if r.development_spend_keur else 0.0),
            reimbursement=_keur(r.development_cost_reimbursement_keur),
            fee=_keur(r.developer_fee_keur),
            net=_keur(r.net_developer_cashflow_keur),
        )
        for r in result.cashflows
    )

    def _metric(key: str, label: str, value: Optional[float], status: Any, fmt) -> DeveloperMetric:
        if value is None:
            return DeveloperMetric(key, label, NA, False, _STATUS_REASON.get(status.value, status.value))
        return DeveloperMetric(key, label, fmt(value), True)

    metrics = (
        _metric("developer_moic", "Developer MOIC", result.developer_moic,
                result.developer_moic_status, _multiple),
        _metric("developer_xirr", "Developer XIRR", result.developer_xirr,
                result.developer_xirr_status, _pct),
    )
    fb = result.fee_basis
    return DeveloperWorkspace(
        state=STATE_ACTIVE,
        state_note="Developer Economics is enabled; all figures are the canonical calculator's output.",
        outcome=result.outcome,
        settlement_date=result.settlement_date.isoformat(),
        spend_rows=spend_rows,
        total_spend=_keur(result.total_development_spend_keur),
        reimbursement=_keur(result.reimbursed_development_cost_keur),
        reimbursement_note=(
            "Reimbursement is a separate project use; it is never the developer fee and never exceeds eligible spend."
        ),
        fee_mode=fb.mode,
        fee_input_display=_fee_input_display(config),
        fee_amount=_keur(result.developer_fee_keur),
        fee_basis=(NA if fb.basis_keur is None else f"{_keur(fb.basis_keur)} kEUR hard CAPEX"),
        fee_basis_authority=fb.basis_authority,
        total_receipts=_keur(result.total_developer_receipts_keur),
        metrics=metrics,
        vector=vector,
        project_uses_total=_keur(uses.total_keur),
        uses_lines=(
            ("Development cost reimbursement", _keur(uses.development_cost_reimbursement_keur)),
            ("Developer fee", _keur(uses.developer_fee_keur)),
        ),
    )


__all__ = [
    "DeveloperMetric", "DeveloperWorkspace", "SpendRow", "VectorRow",
    "STATE_ACTIVE", "STATE_DISABLED", "STATE_INVALID", "build_developer_workspace",
]
