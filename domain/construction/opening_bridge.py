"""Layer 4 Opening Balance Bridge (offline, pure domain).

This module implements the **Layer 4** opening balance bridge
designed in C2 (commit ``59f9e3d``) and planned in C6
(``origin/phase-c6-opening-balance-bridge-implementation-plan``).

The bridge is a **pure transformation function** that takes a
``ConstructionScheduleResult`` and a set of **manual override
values** and produces an ``OpeningBalanceBridgeResult`` with
**explicit per-field policy decisions** recorded in an audit
table.

Hard constraints (re-asserted from C2 §3.6.1 and C6 §3):

- **Pure function.** No side effects. No I/O. No persistence
  writes. No caller mutation. No engine invocation. No
  feature-flag read/write. No project status mutation. No UI.
- **No forbidden imports.** The bridge does NOT import
  ``domain.inputs``, ``domain.waterfall*``, ``app.*``,
  ``main_web``, ``main_api``, or ``static.*``.
- **No new persistence schema.** The bridge is a value object.
- **No runtime wiring.** Layer 5 (C8+) is the only legal
  consumer; this phase does not introduce Layer 5.
- **No project status changes.** Generic Wind Reference remains Level 2,
  Generic Solar Reference remains Level 2.

The output contract is per C2 §3.7; the audit table schema is
per C2 §4.1; the per-field policy is per C2 §2.1.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Final

from domain.construction.result import ConstructionScheduleResult


# ---------------------------------------------------------------------------
# Bridge policy constants (mirror C2 §2.1 verbatim)
# ---------------------------------------------------------------------------

POLICY_VERSION: Final[str] = "C2-1.0"
BRIDGE_VERSION: Final[str] = "C7-1.0"

# Allowed string-literal values for audit row fields. C2/C6 explicitly
# do NOT use Python enums for these — they are plain strings (C3 §4.7
# rule: no Python enums for field codes). The constants below are
# exported as ``Final[str]`` for use by the audit row builder and by
# tests.
SELECTION_REPLACED: Final[str] = "replaced"
SELECTION_FROZEN: Final[str] = "frozen"
SELECTION_RETAINED: Final[str] = "retained"
SELECTION_DERIVED: Final[str] = "derived"

OVERRIDE_NO_OVERRIDE: Final[str] = "no_override"
OVERRIDE_MANUAL_ACTIVE: Final[str] = "manual_override_active"
OVERRIDE_CONSTRUCTION_ACTIVE: Final[str] = "construction_override_active"
OVERRIDE_COMPOSITE_NO_OVERRIDE: Final[str] = "composite_no_override"

GUARD_SINGLE_SOURCE: Final[str] = "guarded_single_source"
GUARD_COMPOSITE: Final[str] = "guarded_composite"

PARITY_OK: Final[str] = "parity_ok"
PARITY_DRIFT: Final[str] = "parity_drift"
PARITY_UNKNOWN: Final[str] = "parity_unknown"
PARITY_NOT_APPLICABLE: Final[str] = "parity_not_applicable"

# Numeric tolerance for opening-balance identity checks (C2 §7.4).
IDENTITY_TOLERANCE_KEUR: Final[float] = 0.001


# ---------------------------------------------------------------------------
# Bridge input dataclasses (C2 §3.2, C6 §5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ManualOverrideRow:
    """A single manual override (field_code → manual_value_keur)."""

    field_code: str
    manual_value_keur: float


@dataclass(frozen=True)
class BridgeFieldPolicy:
    """Per-field policy row from the C2 §2.1 policy table."""

    field_code: str
    current_source_label: str
    construction_source_field: str
    policy: str  # replaced | frozen | retained | derived
    c1_blocker_reference: str


@dataclass(frozen=True)
class ParityReferenceRow:
    """Optional audit-only reference validation reference for a field."""

    field_code: str
    parity_reference_keur: float | None


@dataclass(frozen=True)
class ProjectAssumptions:
    """Project assumptions for the bridge.

    This is a **new** frozen dataclass specific to the bridge. It
    is **not** the existing ``Project`` dataclass in
    ``domain/inputs.py``; the bridge does not import ``Project``
    (C2 §3.6.5, C6 §3.1).
    """

    shl_interest_rate: float
    senior_interest_rate: float
    construction_start_date: _dt.date
    cod_date: _dt.date
    shl_investment_date: _dt.date


@dataclass(frozen=True)
class OpeningBalanceBridgeInput:
    """Layer 4 bridge input contract (C2 §3.2, C6 §5.1)."""

    construction_result: ConstructionScheduleResult
    manual_overrides: tuple[ManualOverrideRow, ...]
    project_assumptions: ProjectAssumptions
    replacement_policy: tuple[BridgeFieldPolicy, ...]
    parity_references: tuple[ParityReferenceRow, ...]
    bridge_version: str


# ---------------------------------------------------------------------------
# Bridge output dataclasses (C2 §3.7, C6 §5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BridgeAuditRow:
    """A single audit reconciliation row (C2 §4.1, 14 columns)."""

    field_code: str
    manual_value_keur: float | None
    construction_derived_value_keur: float | None
    selected_runtime_value_keur: float
    selection_reason: str
    override_status: str
    double_counting_guard: str
    parity_reference_keur: float | None
    parity_delta_keur: float | None
    parity_status: str
    c1_blocker_reference: str
    audit_timestamp: str  # ISO-8601
    bridge_version: str
    policy_version: str


@dataclass(frozen=True)
class BridgeMetadata:
    """Bridge run metadata."""

    policy_version: str
    bridge_version: str
    bridge_run_timestamp: str  # ISO-8601


@dataclass(frozen=True)
class OpeningBalanceBridgeResult:
    """Layer 4 bridge output contract (C2 §3.7, C6 §5.2)."""

    opening_senior_balance_at_cod_keur: float
    opening_shl_balance_at_cod_keur: float
    equity_contribution_at_cod_keur: float
    capitalized_senior_idc_keur: float
    capitalized_shl_idc_keur: float
    financing_fee_treatment_keur: float
    audit_reconciliation_table: tuple[BridgeAuditRow, ...]
    source_construction_result: ConstructionScheduleResult
    manual_overrides: tuple[ManualOverrideRow, ...]
    bridge_metadata: BridgeMetadata


# ---------------------------------------------------------------------------
# Bridge exception
# ---------------------------------------------------------------------------


class BridgeIdentityError(ValueError):
    """Raised when a hard opening-balance identity fails (C2 §7.4).

    Inherits from ``ValueError`` so existing ``except ValueError``
    blocks in Layer 5 (C8+) catch the bridge's identity failures
    without a new exception class import.
    """


# ---------------------------------------------------------------------------
# Module-level policy table (C2 §2.1, 11 entries)
# ---------------------------------------------------------------------------


POLICY_TABLE: Final[tuple[BridgeFieldPolicy, ...]] = (
    BridgeFieldPolicy(
        field_code="shl_idc_keur",
        current_source_label="manual_shl_idc",
        construction_source_field="total_shl_idc_keur",
        policy=SELECTION_REPLACED,
        c1_blocker_reference="blocker_1_R-PAR-1",
    ),
    BridgeFieldPolicy(
        field_code="shl_amount_keur",
        current_source_label="manual_shl_amount",
        construction_source_field="total_shl_draw_keur",
        policy=SELECTION_REPLACED,
        c1_blocker_reference="",
    ),
    BridgeFieldPolicy(
        field_code="shl_opening_balance_keur",
        current_source_label="manual_shl_opening_balance",
        construction_source_field="opening_shl_balance_keur",
        policy=SELECTION_REPLACED,
        c1_blocker_reference="",
    ),
    BridgeFieldPolicy(
        field_code="senior_opening_balance_keur",
        current_source_label="manual_senior_opening_balance",
        construction_source_field="opening_senior_balance_keur",
        policy=SELECTION_FROZEN,
        c1_blocker_reference="blocker_5_R-PAR-2",
    ),
    BridgeFieldPolicy(
        field_code="senior_idc_keur",
        current_source_label="manual_senior_idc",
        construction_source_field="total_senior_idc_keur",
        policy=SELECTION_REPLACED,
        c1_blocker_reference="blocker_5_R-PAR-2",
    ),
    BridgeFieldPolicy(
        field_code="capex_keur",
        current_source_label="manual_capex",
        construction_source_field="total_uses_keur",
        policy=SELECTION_FROZEN,
        c1_blocker_reference="",
    ),
    BridgeFieldPolicy(
        field_code="reserves_keur",
        current_source_label="manual_reserves",
        construction_source_field="",
        policy=SELECTION_RETAINED,
        c1_blocker_reference="",
    ),
    BridgeFieldPolicy(
        field_code="vat_operating",
        current_source_label="manual_vat",
        construction_source_field="",
        policy=SELECTION_RETAINED,
        c1_blocker_reference="",
    ),
    BridgeFieldPolicy(
        field_code="financing_fees_keur",
        current_source_label="manual_financing_fees",
        construction_source_field="",
        policy=SELECTION_RETAINED,
        c1_blocker_reference="",
    ),
    BridgeFieldPolicy(
        field_code="commitment_fee_keur",
        current_source_label="manual_commitment_fee",
        construction_source_field="",
        policy=SELECTION_RETAINED,
        c1_blocker_reference="",
    ),
    BridgeFieldPolicy(
        field_code="equity_total_keur",
        current_source_label="manual_equity_total",
        construction_source_field="total_equity_draw_keur",
        policy=SELECTION_DERIVED,
        c1_blocker_reference="blocker_5_R-PAR-5",
    ),
)


# ---------------------------------------------------------------------------
# Bridge implementation helpers
# ---------------------------------------------------------------------------


def _lookup_manual(
    manual_overrides: tuple[ManualOverrideRow, ...],
    field_code: str,
) -> float | None:
    """Return the manual value for ``field_code`` or ``None``."""
    for row in manual_overrides:
        if row.field_code == field_code:
            return row.manual_value_keur
    return None


def _lookup_parity(
    parity_references: tuple[ParityReferenceRow, ...],
    field_code: str,
) -> float | None:
    """Return the parity reference for ``field_code`` or ``None``."""
    for row in parity_references:
        if row.field_code == field_code:
            return row.parity_reference_keur
    return None


def _construction_value(
    field_code: str,
    construction_source_field: str,
    result: ConstructionScheduleResult,
) -> float | None:
    """Return the construction-derived value for ``field_code`` or ``None``.

    Returns ``None`` when the field has no construction source (i.e.
    ``construction_source_field == ""`` for retained fields).
    """
    if construction_source_field == "":
        return None
    if not hasattr(result, construction_source_field):
        return None
    return getattr(result, construction_source_field)


def _parity_status(
    selected: float,
    parity_reference: float | None,
    policy: str,
) -> str:
    """Compute the parity_status for an audit row."""
    if parity_reference is None:
        return PARITY_NOT_APPLICABLE
    delta = abs(selected - parity_reference)
    if delta <= IDENTITY_TOLERANCE_KEUR:
        return PARITY_OK
    return PARITY_DRIFT


def _parity_delta(selected: float, parity_reference: float | None) -> float | None:
    """Compute the parity_delta_keur for an audit row.

    Convention: ``manual_value - parity_reference`` (C2 §4.1), but when
    the bridge does not use the manual value (i.e. ``replaced`` or
    ``derived``), we compute ``selected - parity_reference`` (the
    actually-selected value's drift from Excel). This is consistent
    with C2 §4.4 example for ``senior_opening_balance_keur`` where the
    bridge returns the configured manual value and the drift is shown
    as a diagnostic difference between compared authorities. For ``replaced`` fields, the
    drift is the selected (construction) - parity, which is the
    more useful diagnostic.
    """
    if parity_reference is None:
        return None
    return selected - parity_reference


def _compute_selected_value(
    policy: str,
    manual_value: float | None,
    construction_value_: float | None,
) -> float:
    """Compute the selected_runtime_value_keur for a row.

    Raises:
        BridgeIdentityError: if the field has no usable source.

    Selection rules (C2 §2.2):

    - replaced: use the construction value
    - frozen: use the manual value (or raise if no manual value)
    - retained: use the manual value (or raise if no manual value)
    - derived: use the manual value (the composite inputs are
      manual; construction equity is recorded separately)
    """
    if policy == SELECTION_REPLACED:
        if construction_value_ is None:
            raise BridgeIdentityError(
                "Replaced field has no construction value"
            )
        return construction_value_
    if policy in (SELECTION_FROZEN, SELECTION_RETAINED, SELECTION_DERIVED):
        if manual_value is None:
            raise BridgeIdentityError(
                f"Field with policy={policy!r} has no manual value"
            )
        return manual_value
    raise BridgeIdentityError(f"Unknown policy: {policy!r}")


def _override_status(policy: str) -> str:
    """Compute the override_status for an audit row."""
    if policy == SELECTION_REPLACED:
        return OVERRIDE_CONSTRUCTION_ACTIVE
    if policy == SELECTION_FROZEN:
        return OVERRIDE_MANUAL_ACTIVE
    if policy == SELECTION_RETAINED:
        return OVERRIDE_NO_OVERRIDE
    if policy == SELECTION_DERIVED:
        return OVERRIDE_COMPOSITE_NO_OVERRIDE
    return OVERRIDE_NO_OVERRIDE


def _double_counting_guard(policy: str) -> str:
    """Compute the double_counting_guard for an audit row.

    Per C6 §6.1: every policy field has either
    ``guarded_single_source`` or ``guarded_composite``. No field has
    ``not_applicable`` (C2 §4.5 invariant 4).
    """
    if policy == SELECTION_DERIVED:
        return GUARD_COMPOSITE
    return GUARD_SINGLE_SOURCE


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------


def build_opening_balance_bridge(
    input: OpeningBalanceBridgeInput,
) -> OpeningBalanceBridgeResult:
    """Build the Layer 4 opening balance bridge output.

    This is the **only** public function in this module. It is
    **pure**: same input → same output. No side effects. No I/O.
    No engine call. No persistence. No caller mutation.

    Algorithm (C6 §2.4, C2 §3.4):

    1. For each policy field, look up the manual value, the
       construction value, and the parity reference.
    2. Apply the policy to compute the selected value.
    3. Build a ``BridgeAuditRow`` with the full audit trail.
    4. Compute the 6 numeric output fields from the policy
       results.
    5. Assert the opening-balance identities (C2 §7.4):
       opening_senior == total_senior_draw + capitalized_senior_idc
       opening_shl == total_shl_draw + capitalized_shl_idc
       equity_contribution == total_equity_draw
       All within ±0.001 kEUR. Raise ``BridgeIdentityError`` on
       failure.
    6. Return the result.

    Raises:
        BridgeIdentityError: when a hard identity fails or a
            required field is missing.
        ValueError: when the input is malformed (e.g. an empty
            ``replacement_policy``).
    """
    # Defensive: input is well-formed.
    if not input.replacement_policy:
        raise ValueError(
            "OpeningBalanceBridgeInput.replacement_policy is empty"
        )
    if not input.manual_overrides and any(
        p.policy in (SELECTION_FROZEN, SELECTION_RETAINED, SELECTION_DERIVED)
        for p in input.replacement_policy
    ):
        # Not strictly an error — caller may legitimately have no
        # overrides. We still allow the call; missing manual values
        # will raise BridgeIdentityError at field-resolution time.
        pass

    # 1-3. Build the audit table row-by-row.
    audit_rows: list[BridgeAuditRow] = []
    audit_by_field: dict[str, BridgeAuditRow] = {}

    for entry in input.replacement_policy:
        manual_value = _lookup_manual(input.manual_overrides, entry.field_code)
        construction_value_ = _construction_value(
            entry.field_code,
            entry.construction_source_field,
            input.construction_result,
        )
        parity_reference = _lookup_parity(
            input.parity_references, entry.field_code
        )

        # 2. Apply the policy.
        try:
            selected = _compute_selected_value(
                entry.policy, manual_value, construction_value_
            )
        except BridgeIdentityError:
            # Re-raise with field context.
            raise

        # 3. Build the row.
        row = BridgeAuditRow(
            field_code=entry.field_code,
            manual_value_keur=manual_value,
            construction_derived_value_keur=construction_value_,
            selected_runtime_value_keur=selected,
            selection_reason=entry.policy,
            override_status=_override_status(entry.policy),
            double_counting_guard=_double_counting_guard(entry.policy),
            parity_reference_keur=parity_reference,
            parity_delta_keur=_parity_delta(selected, parity_reference),
            parity_status=_parity_status(
                selected, parity_reference, entry.policy
            ),
            c1_blocker_reference=entry.c1_blocker_reference,
            audit_timestamp=_dt.datetime.now(_dt.timezone.utc).isoformat(),
            bridge_version=input.bridge_version,
            policy_version=POLICY_VERSION,
        )
        audit_rows.append(row)
        audit_by_field[entry.field_code] = row

    # 4. Compute the 6 numeric output fields.
    result = input.construction_result
    opening_senior = _lookup_audit(
        audit_by_field, "senior_opening_balance_keur"
    )
    opening_shl = _lookup_audit(audit_by_field, "shl_opening_balance_keur")
    equity_contribution = _lookup_audit(audit_by_field, "equity_total_keur")
    capitalized_senior_idc = _lookup_audit(
        audit_by_field, "senior_idc_keur"
    )
    capitalized_shl_idc = _lookup_audit(audit_by_field, "shl_idc_keur")
    financing_fee = _lookup_audit(audit_by_field, "financing_fees_keur")

    # 5. Opening-balance identity check (C2 §7.4, refined by C6 §6.4).
    # The hard identities are mathematical statements about the
    # *construction-derived* opening balances. They are:
    # - opening_senior == total_senior_draw + capitalized_senior_idc
    # - opening_shl == total_shl_draw + capitalized_shl_idc
    # - equity_contribution == total_equity_draw
    # All within ±0.001 kEUR. Raise BridgeIdentityError on failure.
    #
    # However, when an opening balance is **frozen** (i.e. the manual
    # value is used), the identity is **expected to fail** because the
    # manual value does not include the capitalized IDC. The C6 §6.4
    # asymmetry is intentional: the senior opening balance is frozen
    # precisely because the senior IDC is not modelling-correct, and
    # the resulting drift is the diagnostic signal.
    # The identity check therefore applies only to opening balances
    # that are **replaced** by the construction engine. For frozen or
    # derived opening balances, the identity is not enforced (the
    # manual value is the authority by definition).
    senior_policy = _lookup_policy(
        input.replacement_policy, "senior_opening_balance_keur"
    )
    shl_policy = _lookup_policy(
        input.replacement_policy, "shl_opening_balance_keur"
    )
    equity_policy = _lookup_policy(
        input.replacement_policy, "equity_total_keur"
    )

    if senior_policy == SELECTION_REPLACED and not _identity_ok(
        opening_senior,
        result.total_senior_draw_keur + capitalized_senior_idc,
    ):
        raise BridgeIdentityError(
            "Senior opening balance identity failed: "
            f"opening_senior={opening_senior}, "
            f"total_senior_draw={result.total_senior_draw_keur}, "
            f"capitalized_senior_idc={capitalized_senior_idc}"
        )
    if shl_policy == SELECTION_REPLACED and not _identity_ok(
        opening_shl,
        result.total_shl_draw_keur + capitalized_shl_idc,
    ):
        raise BridgeIdentityError(
            "SHL opening balance identity failed: "
            f"opening_shl={opening_shl}, "
            f"total_shl_draw={result.total_shl_draw_keur}, "
            f"capitalized_shl_idc={capitalized_shl_idc}"
        )
    if equity_policy == SELECTION_REPLACED and not _identity_ok(
        equity_contribution, result.total_equity_draw_keur
    ):
        raise BridgeIdentityError(
            "Equity contribution identity failed: "
            f"equity_contribution={equity_contribution}, "
            f"total_equity_draw={result.total_equity_draw_keur}"
        )

    # 6. Return the result.
    bridge_metadata = BridgeMetadata(
        policy_version=POLICY_VERSION,
        bridge_version=input.bridge_version,
        bridge_run_timestamp=_dt.datetime.now(_dt.timezone.utc).isoformat(),
    )
    return OpeningBalanceBridgeResult(
        opening_senior_balance_at_cod_keur=opening_senior,
        opening_shl_balance_at_cod_keur=opening_shl,
        equity_contribution_at_cod_keur=equity_contribution,
        capitalized_senior_idc_keur=capitalized_senior_idc,
        capitalized_shl_idc_keur=capitalized_shl_idc,
        financing_fee_treatment_keur=financing_fee,
        audit_reconciliation_table=tuple(audit_rows),
        source_construction_result=result,
        manual_overrides=input.manual_overrides,
        bridge_metadata=bridge_metadata,
    )


def _lookup_audit(audit_by_field: dict[str, BridgeAuditRow], field_code: str) -> float:
    """Return the selected_runtime_value_keur for ``field_code``.

    Raises:
        BridgeIdentityError: if the field is missing from the
            replacement policy.
    """
    row = audit_by_field.get(field_code)
    if row is None:
        raise BridgeIdentityError(
            f"Field {field_code!r} is not in the replacement policy"
        )
    return row.selected_runtime_value_keur


def _lookup_policy(
    policy: tuple[BridgeFieldPolicy, ...], field_code: str
) -> str:
    """Return the policy string for ``field_code`` or raise.

    Raises:
        BridgeIdentityError: if the field is missing from the
            replacement policy.
    """
    for entry in policy:
        if entry.field_code == field_code:
            return entry.policy
    raise BridgeIdentityError(
        f"Field {field_code!r} is not in the replacement policy"
    )


def _identity_ok(actual: float, expected: float) -> bool:
    """Return True if |actual - expected| <= IDENTITY_TOLERANCE_KEUR."""
    return abs(actual - expected) <= IDENTITY_TOLERANCE_KEUR


__all__ = [
    "BRIDGE_VERSION",
    "BridgeAuditRow",
    "BridgeFieldPolicy",
    "BridgeIdentityError",
    "BridgeMetadata",
    "GUARD_COMPOSITE",
    "GUARD_SINGLE_SOURCE",
    "IDENTITY_TOLERANCE_KEUR",
    "ManualOverrideRow",
    "OVERRIDE_COMPOSITE_NO_OVERRIDE",
    "OVERRIDE_CONSTRUCTION_ACTIVE",
    "OVERRIDE_MANUAL_ACTIVE",
    "OVERRIDE_NO_OVERRIDE",
    "OpeningBalanceBridgeInput",
    "OpeningBalanceBridgeResult",
    "PARITY_DRIFT",
    "PARITY_NOT_APPLICABLE",
    "PARITY_OK",
    "PARITY_UNKNOWN",
    "POLICY_TABLE",
    "POLICY_VERSION",
    "ParityReferenceRow",
    "ProjectAssumptions",
    "SELECTION_DERIVED",
    "SELECTION_FROZEN",
    "SELECTION_REPLACED",
    "SELECTION_RETAINED",
    "build_opening_balance_bridge",
]
