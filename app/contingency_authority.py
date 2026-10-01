"""Typed contingency percentage authority for CAPEX C.13 and OPEX B.13.

Pure, deterministic helpers (no I/O).  The frozen ``finco_core`` /
``financial_engine`` namespaces are untouched: the authority is applied to the
``CapexStructure`` / ``OpexItem`` tuple *before* the engine runs, exactly where
persisted custom sub-lines are already folded.

Economic contract
-----------------
CAPEX C.13 (basis ``OTHER_ELIGIBLE_CAPEX``)::

    basis_amount        = sum(amount of every ELIGIBLE category)   [kEUR]
    contingency_amount  = contingency_pct / 100 * basis_amount     [kEUR]

ELIGIBLE = C.01-C.12 and C.14-C.16 (custom rows included, because they fold
into those categories).  EXCLUDED = C.13 itself (self-reference) and the
derived financing categories C.17 / C.18 (IDC, commitment/bank fees, other
financial, VAT-facility costs, reserve accounts): those are *functions of total
CAPEX / debt sizing*, so including them would make the contingency circular.

OPEX B.13 (basis ``SAME_PERIOD_OTHER_OPEX``) is evaluated period by period by
the engine::

    contingency[t] = contingency_pct / 100 * sum(other OPEX groups[t])

No lifetime basis is invented.

Absence of an authority (``None``) means "keep the existing reference amount":
protected reference models therefore remain numerically identical.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace as _dc_replace
from typing import Any, Mapping, Optional

REPLAY_KEY = "contingency_authority"
SCENARIO_OVERRIDE_KEY = "_contingency_pct_overrides"

CAPEX_BASIS_OTHER_ELIGIBLE = "OTHER_ELIGIBLE_CAPEX"
OPEX_BASIS_SAME_PERIOD = "SAME_PERIOD_OTHER_OPEX"

# category code -> CapexStructure field (C.08 and C.11 share audit_legal).
CAPEX_ELIGIBLE_CATEGORIES: tuple[str, ...] = (
    "C.01", "C.02", "C.03", "C.04", "C.05", "C.06", "C.07", "C.08", "C.09",
    "C.10", "C.11", "C.12", "C.14", "C.15", "C.16",
)
CAPEX_ELIGIBLE_FIELDS: tuple[str, ...] = (
    "epc_contract", "production_units", "epc_other", "grid_connection",
    "ops_prep", "insurances", "lease_tax", "construction_mgmt_a",
    "commissioning", "audit_legal", "construction_mgmt_b", "taxes",
    "project_acquisition", "project_rights",
)
CAPEX_EXCLUDED_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("C.13", "self (contingency cannot be its own basis)"),
    ("C.17", "derived financing costs depend on total CAPEX / debt (circular)"),
    ("C.18", "reserve accounts depend on debt service (circular)"),
)
OPEX_EXCLUDED_GROUPS: tuple[tuple[str, str], ...] = (
    ("B.13", "self (contingency cannot be its own basis)"),
)


@dataclass(frozen=True)
class ContingencyLineage:
    """Everything a reviewer needs to reproduce the contingency number."""

    target: str                       # "C.13" | "B.13"
    mode: str                         # "percentage" | "reference_amount"
    source: str                       # "project" | "scenario_override" | "reference_amount"
    pct: Optional[float]
    basis_mode: str
    included_categories: tuple[str, ...]
    excluded_categories: tuple[tuple[str, str], ...]
    basis_amount_keur: Optional[float]   # None = unavailable (never 0)
    amount_keur: Optional[float]         # None = unavailable (never 0)
    status: str                          # "calculated" | "zero_basis" | "reference_amount" | "unavailable"
    formula: str
    # OPEX only: the real period-by-period series (no lifetime sum is invented).
    period_basis_keur: Optional[tuple] = None
    period_amount_keur: Optional[tuple] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target, "mode": self.mode, "source": self.source,
            "pct": self.pct, "basis_mode": self.basis_mode,
            "included_categories": list(self.included_categories),
            "excluded_categories": [list(x) for x in self.excluded_categories],
            "basis_amount_keur": self.basis_amount_keur,
            "amount_keur": self.amount_keur, "status": self.status,
            "formula": self.formula,
            "period_basis_keur": None if self.period_basis_keur is None else list(self.period_basis_keur),
            "period_amount_keur": None if self.period_amount_keur is None else list(self.period_amount_keur),
        }


def validate_pct(raw: Any) -> float:
    """Strict 0-100 finite number; bool/str/NaN/Inf/out-of-range raise."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError("contingency_pct must be numeric")
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError("contingency_pct must be finite")
    if value < 0 or value > 100:
        raise ValueError("contingency_pct must be between 0 and 100")
    return value


def read_authority(replay_metadata: Optional[Mapping[str, Any]], kind: str) -> Optional[float]:
    """Stored project pct for ``kind`` ("capex" | "opex"); None = no authority."""
    block = (replay_metadata or {}).get(REPLAY_KEY)
    if not isinstance(block, Mapping):
        return None
    raw = block.get(f"{kind}_pct")
    return None if raw is None else validate_pct(raw)


def write_authority(
    replay_metadata: Optional[Mapping[str, Any]], kind: str, pct: Optional[float]
) -> dict[str, Any]:
    """Return a copy of replay_metadata with the authority set (None clears)."""
    out = dict(replay_metadata or {})
    block = dict(out.get(REPLAY_KEY) or {})
    if pct is None:
        block.pop(f"{kind}_pct", None)
    else:
        block[f"{kind}_pct"] = validate_pct(pct)
    if block:
        out[REPLAY_KEY] = block
    else:
        out.pop(REPLAY_KEY, None)
    return out


def resolve_pct(
    replay_metadata: Optional[Mapping[str, Any]],
    scenario_overrides: Optional[Mapping[str, Any]],
    kind: str,
) -> tuple[Optional[float], str]:
    """Effective pct and its source.  Scenario override beats project value."""
    ov = (scenario_overrides or {}).get(SCENARIO_OVERRIDE_KEY)
    if isinstance(ov, Mapping) and ov.get(kind) is not None:
        return validate_pct(ov[kind]), "scenario_override"
    stored = read_authority(replay_metadata, kind)
    if stored is not None:
        return stored, "project"
    return None, "reference_amount"


# --------------------------------------------------------------------- CAPEX
def capex_basis_keur(capex: Any) -> float:
    return sum(float(getattr(capex, f).amount_keur) for f in CAPEX_ELIGIBLE_FIELDS)


def capex_lineage(
    *, basis_keur: Optional[float], pct: Optional[float], source: str,
    reference_amount_keur: Optional[float] = None,
) -> ContingencyLineage:
    common = dict(
        target="C.13", basis_mode=CAPEX_BASIS_OTHER_ELIGIBLE,
        included_categories=CAPEX_ELIGIBLE_CATEGORIES,
        excluded_categories=CAPEX_EXCLUDED_CATEGORIES,
    )
    if pct is None:
        return ContingencyLineage(
            mode="reference_amount", source="reference_amount", pct=None,
            basis_amount_keur=basis_keur, amount_keur=reference_amount_keur,
            status="reference_amount" if reference_amount_keur is not None else "unavailable",
            formula="C.13 = reference amount (no percentage authority set)", **common)
    if basis_keur is None:
        return ContingencyLineage(
            mode="percentage", source=source, pct=pct, basis_amount_keur=None,
            amount_keur=None, status="unavailable",
            formula=f"C.13 = {pct:g}% x basis (basis unavailable)", **common)
    amount = pct / 100.0 * basis_keur
    return ContingencyLineage(
        mode="percentage", source=source, pct=pct, basis_amount_keur=basis_keur,
        amount_keur=amount, status="calculated" if basis_keur != 0 else "zero_basis",
        formula=f"C.13 = {pct:g}% x {basis_keur:,.2f} kEUR (eligible CAPEX excl. C.13/C.17/C.18)",
        **common)


def _basis_weighted_spending(capex: Any) -> tuple[float, tuple[float, ...]]:
    """(y0_share, spending_profile) of the eligible basis, amount-weighted.

    Contingency has no timing of its own: it is spent pro rata to the CAPEX it
    covers.  Only used when the existing contingency item carries no valid
    spending profile (the zero-amount reference placeholder), because the
    engine fails closed on a non-zero item whose shares do not sum to 1.
    """
    items = [getattr(capex, f) for f in CAPEX_ELIGIBLE_FIELDS]
    items = [i for i in items if float(i.amount_keur) > 0]
    total = sum(float(i.amount_keur) for i in items)
    if total <= 0:
        return 1.0, ()
    width = max((len(i.spending_profile) for i in items), default=0)
    y0 = sum(float(i.amount_keur) * float(i.y0_share) for i in items) / total
    prof = [
        sum(
            float(i.amount_keur) * (float(i.spending_profile[k]) if k < len(i.spending_profile) else 0.0)
            for i in items
        ) / total
        for k in range(width)
    ]
    norm = y0 + sum(prof)
    if norm <= 0:
        return 1.0, ()
    return y0 / norm, tuple(p / norm for p in prof)


def apply_capex_contingency(capex: Any, pct: Optional[float]) -> Any:
    """Set ``contingencies`` = pct% x eligible basis.  ``None`` = unchanged."""
    if pct is None:
        return capex
    pct = validate_pct(pct)
    amount = pct / 100.0 * capex_basis_keur(capex)
    item = capex.contingencies
    changes: dict[str, Any] = {"amount_keur": amount}
    shares = float(item.y0_share) + sum(item.spending_profile)
    if amount > 0 and abs(shares - 1.0) > 0.001:
        y0, prof = _basis_weighted_spending(capex)
        changes.update(y0_share=y0, spending_profile=prof)
    return _dc_replace(capex, contingencies=_dc_replace(item, **changes))


# ---------------------------------------------------------------------- OPEX
def apply_opex_contingency(opex: Any, pct: Optional[float]) -> Any:
    """Set the B.13 ``percentage_of_opex`` (period-by-period in the engine)."""
    if pct is None:
        return opex
    pct = validate_pct(pct)
    frac = pct / 100.0
    items = list(opex)
    found = False
    for idx, item in enumerate(items):
        if float(getattr(item, "percentage_of_opex", 0.0) or 0.0) > 0 or (
            getattr(item, "name", "") == OPEX_CONTINGENCY_ITEM_NAME
        ):
            items[idx] = _dc_replace(
                item, percentage_of_opex=frac, y1_amount_keur=0.0,
                annual_inflation=0.0, step_changes=(),
            )
            found = True
    if not found and frac > 0:
        from finco_core.inputs import OpexItem
        items.append(OpexItem(
            name=OPEX_CONTINGENCY_ITEM_NAME, y1_amount_keur=0.0,
            annual_inflation=0.0, percentage_of_opex=frac,
        ))
    return tuple(items)


OPEX_CONTINGENCY_ITEM_NAME = "Contingency"


def opex_lineage(*, pct: Optional[float], source: str,
                 period_basis_keur: Optional[list], period_amount_keur: Optional[list]
                 ) -> ContingencyLineage:
    common = dict(
        target="B.13", basis_mode=OPEX_BASIS_SAME_PERIOD,
        included_categories=("B.01-B.12 (same period)",),
        excluded_categories=OPEX_EXCLUDED_GROUPS,
    )
    if pct is None:
        return ContingencyLineage(
            mode="reference_amount", source="reference_amount", pct=None,
            basis_amount_keur=None, amount_keur=None, status="reference_amount",
            formula="B.13 = reference rule (no percentage authority set)", **common)
    return ContingencyLineage(
        mode="percentage", source=source, pct=pct,
        # Headline figures are Year 1 (period 1); the full series is in period_*.
        basis_amount_keur=period_basis_keur[0] if period_basis_keur else None,
        amount_keur=period_amount_keur[0] if period_amount_keur else None,
        status="calculated" if period_basis_keur else "unavailable",
        formula=f"B.13[t] = {pct:g}% x sum(B.01-B.12)[t]  (Year 1 shown)",
        period_basis_keur=None if period_basis_keur is None else tuple(period_basis_keur),
        period_amount_keur=None if period_amount_keur is None else tuple(period_amount_keur),
        **common)
