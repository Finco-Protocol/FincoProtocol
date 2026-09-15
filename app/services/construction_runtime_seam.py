"""Phase C9 — Layer 5 Runtime Seam Scaffolding (NO runtime promotion).

This module is the **first** implementation phase of the seam
that connects the Layer 4 bridge output to the runtime waterfall.

SCOPE (per C8 §7.1):

The seam module is **scaffolding only**. It implements:

1. ``assert_no_construction_runtime_promotion`` — the no-promotion
   guard designed in C8 §5. The guard is the structural mechanism
   that prevents accidental routing of bridge output into runtime
   before C10/C11 explicitly opt a project in.

2. ``ConstructionRuntimeSeam`` — a read-only visibility helper
   that exposes bridge output to audit consumers. The seam
   never mutates runtime state, never writes to the waterfall,
   never flips feature flags, and never consumes the construction
   engine.

3. ``ConstructionSeamPolicy`` — a thin enum/literal layer that
   mirrors the C7 POLICY_TABLE policy names so the guard and
   seam helpers can speak the same vocabulary without depending
   on the bridge module's private types.

NON-SCOPE (per C8 §7.2 — explicit MUST NOTs):

- The seam does **NOT** flip feature flags. The global
  ``use_construction_schedule_engine`` flag remains
  ``False`` in ``domain/inputs.py`` (default-off).
- The seam does **NOT** route values into the waterfall. It is
  a read-side adapter; the waterfall continues to consume
  manual inputs.
- The seam does **NOT** change runtime outputs, formulas,
  tax, debt, depreciation, CFADS, or persistence.
- The seam does **NOT** change UI, persistence, or schema.
- The seam does **NOT** call the construction engine or the
  bridge's ``build_opening_balance_bridge`` function. It only
  consumes the *types* of the bridge (specifically the
  ``POLICY_TABLE`` constant) for policy-name lookups.

WHAT THE GUARD DOES (C8 §5.1, §5.2):

The guard enforces that bridge output cannot be promoted into
runtime without explicit, per-field, per-call approval:

- **frozen fields**: always raise ``PermissionError``. There
  is no override, no flag flip, and no future C-phase that
  can enable this. Frozen is structural.
- **senior_idc_keur** (``replaced``, R-PAR-2): raise unless
  ``rpar2_resolved=True``. The fail-closed default means
  C10 cannot promote this field without first resolving or
  formally accepting R-PAR-2.
- **other replaced fields**: raise unless
  ``promotion_requested=True``.
- **derived fields**: raise unless ``promotion_requested=True``
  AND ``parity_ok`` (parity is supplied as a keyword argument;
  the guard does not compute it).
- **retained fields**: never raise. These fields are not
  bridge-sourced, so the guard is a no-op for them.

The guard is callable from tests and from future controlled-
enablement PRs (C10/C11). It is **NOT** wired into the live
waterfall path in C9. C9 is structural, not numerical.

IMPORT CONTRACT (C8 §6):

This module is the **only** module that may import
``domain.construction.opening_bridge`` in C9. The C8
import-contract test exempts this module from the
forbidden-importer list. The seam module does **not**
re-export or expose the bridge's public symbols to the
rest of the runtime. It only uses ``POLICY_TABLE`` for
policy-name validation.

CALLING CONVENTION:

The guard is invoked by callers that are about to route a
bridge-produced value into runtime. C10/C11 will call it
once per promoted field. C9 does not call it from any
runtime path; it only ships the function for future use.

This module is heavily commented because it is a structural
gate. The intent of the no-promotion rule must be obvious
to anyone reading the code, including future reviewers of
C10/C11 promotion PRs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Mapping

# Import ONLY the POLICY_TABLE constant and the BridgeFieldPolicy type
# from the bridge. We do NOT import build_opening_balance_bridge or
# OpeningBalanceBridgeResult. This is the bridge's read-only surface
# for the seam, and the import is the explicit exception to the C8
# import-contract test (see tests/test_phase_c9_construction_runtime_seam.py).
from domain.construction.opening_bridge import POLICY_TABLE, BridgeFieldPolicy


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Module version. Bump only when guard behavior changes.
SEAM_VERSION: Final[str] = "C9-1.0"

#: Mirror of C7 POLICY_VERSION. The seam does not depend on the bridge
#: at runtime for this constant; it is included so the seam can self-
#: describe the POLICY_TABLE schema it expects.
SEAM_POLICY_VERSION: Final[str] = "C2-1.0"

#: Policy names. Mirrors the C7 POLICY_TABLE.policy field values.
#: Defined here as a Final literal set so the guard can validate input
#: without depending on the bridge module's internals.
POLICY_FROZEN: Final[str] = "frozen"
POLICY_REPLACED: Final[str] = "replaced"
POLICY_RETAINED: Final[str] = "retained"
POLICY_DERIVED: Final[str] = "derived"

#: The set of valid policy names. Used by the guard for input validation.
VALID_POLICIES: Final[frozenset[str]] = frozenset(
    {POLICY_FROZEN, POLICY_REPLACED, POLICY_RETAINED, POLICY_DERIVED}
)

#: Fields that are subject to R-PAR-2 (C1). The guard treats these as
#: "replaced" but blocks promotion until R-PAR-2 is resolved or
#: formally accepted. The constant is a frozenset so it can be queried
#: cheaply without re-allocating per call.
RPAR2_FIELDS: Final[frozenset[str]] = frozenset({"senior_idc_keur"})

#: The full set of fields that the seam is aware of. The guard uses
#: this to validate that ``field_code`` is a known construction-bridge
#: field. The list is sourced from the bridge's POLICY_TABLE at import
#: time and frozen for the lifetime of the process.
SEAM_KNOWN_FIELDS: Final[frozenset[str]] = frozenset(
    entry.field_code for entry in POLICY_TABLE
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ConstructionSeamError(Exception):
    """Base class for all Construction Runtime Seam errors.

    All exceptions raised by the seam module inherit from this class.
    This makes it easy for callers (C10/C11) to catch any seam-level
    error without depending on the specific subclass.
    """


class InvalidPolicyError(ConstructionSeamError, ValueError):
    """Raised when a guard call supplies a policy that is not in
    ``VALID_POLICIES``.

    This is a programmer error (caller passed a bad literal), not a
    promotion-blocked condition. It is separate from
    ``PromotionBlockedError`` so tests can distinguish "I called the
    guard wrong" from "the guard is doing its job".
    """


class UnknownFieldError(ConstructionSeamError, ValueError):
    """Raised when a guard call supplies a ``field_code`` that is not
    in ``SEAM_KNOWN_FIELDS``.

    This is also a programmer error. The guard refuses to evaluate
    fields it does not know about; this is a defensive measure to
    prevent typos in ``field_code`` from silently passing.
    """


class PromotionBlockedError(ConstructionSeamError, PermissionError):
    """Raised by ``assert_no_construction_runtime_promotion`` when a
    promotion request is structurally blocked.

    Subclasses ``PermissionError`` because the guard is a permission
    gate: "this caller is not allowed to promote this field at this
    time" is a permission, not a value, condition.

    Tests assert on this specific exception. C10/C11 will catch this
    exception (or one of its more specific subclasses) to decide
    whether to route a bridge value into the waterfall.

    Note: this is the C9-class of error. The C8 design §5.1 specified
    ``PermissionError`` directly; C9 subclasses it so callers can
    catch ``PermissionError`` for compatibility but also catch
    ``PromotionBlockedError`` for seam-specific handling.
    """


# ---------------------------------------------------------------------------
# Guard (C8 §5.1, §5.2)
# ---------------------------------------------------------------------------


def assert_no_construction_runtime_promotion(
    *,
    field_code: str,
    policy: str,
    promotion_requested: bool,
    rpar2_resolved: bool = False,
    parity_ok: bool = False,
) -> None:
    """Raise if bridge output is being routed into runtime without
    explicit approval.

    This is the C9 implementation of the guard designed in C8 §5.1.
    The behavior matrix is exactly the table in C8 §5.2.

    Parameters
    ----------
    field_code:
        The construction-bridge field code (e.g. ``shl_idc_keur``,
        ``senior_opening_balance_keur``). Must be a member of
        ``SEAM_KNOWN_FIELDS``.
    policy:
        The policy assigned to the field in the C7 POLICY_TABLE.
        Must be one of ``frozen``, ``replaced``, ``retained``,
        ``derived``. The guard cross-checks this against
        ``POLICY_TABLE`` to ensure the caller is not lying about
        the field's policy.
    promotion_requested:
        Whether the caller is asking the seam to promote this
        field's bridge value into the runtime waterfall. The guard
        raises for non-retained fields when this is ``False``.
    rpar2_resolved:
        Whether the C1 R-PAR-2 caveat (senior IDC effective-rate
        caveat) has been resolved or formally accepted. Defaults
        to ``False`` (fail-closed). Required for ``senior_idc_keur``
        to be promotable.
    parity_ok:
        Whether the bridge parity check for this field is OK. Only
        relevant for ``derived`` fields. The guard does NOT compute
        parity; the caller must supply it based on the bridge
        result's ``BridgeAuditRow.parity`` field. Defaults to
        ``False`` (fail-closed).

    Raises
    ------
    UnknownFieldError:
        If ``field_code`` is not in ``SEAM_KNOWN_FIELDS``.
    InvalidPolicyError:
        If ``policy`` is not in ``VALID_POLICIES``, or if
        ``policy`` does not match the C7 POLICY_TABLE entry for
        ``field_code``.
    PromotionBlockedError:
        If the (field, policy, promotion_requested, rpar2_resolved,
        parity_ok) tuple is structurally blocked from promotion
        per C8 §5.2.

    Returns
    -------
    None
        The guard returns ``None`` on success (i.e. promotion is
        structurally permitted by the C8/C9 policy). The caller
        may then proceed to route the bridge value into the
        runtime waterfall (or not — the guard is a gate, not an
        order).

    Notes
    -----
    The guard is a **structural** mechanism, not a runtime
    mechanism. It does not change runtime state, does not write
    to the waterfall, and does not flip feature flags. It is a
    pure function: given the same inputs, it always returns the
    same answer (raise or return None).

    The guard is **not** wired into the live waterfall path in
    C9. C9 is the first phase to implement the guard; C10/C11
    are the phases that will call it from the waterfall path
    for specific projects. Until then, the guard is callable
    from tests and from any controlled-enablement code path
    (e.g. an opt-in CLI command) but not from the live runtime.
    """
    # -----------------------------------------------------------------
    # Input validation (programmer error guards)
    # -----------------------------------------------------------------

    if field_code not in SEAM_KNOWN_FIELDS:
        raise UnknownFieldError(
            f"field_code {field_code!r} is not a known construction-bridge "
            f"field. Known fields: {sorted(SEAM_KNOWN_FIELDS)}"
        )

    if policy not in VALID_POLICIES:
        raise InvalidPolicyError(
            f"policy {policy!r} is not a valid construction-bridge policy. "
            f"Valid policies: {sorted(VALID_POLICIES)}"
        )

    # Cross-check the supplied policy against the C7 POLICY_TABLE entry
    # for this field. This prevents a caller from claiming
    # ``policy='retained'`` for a field whose actual policy is
    # ``'frozen'``, which would bypass the guard.
    table_entry: BridgeFieldPolicy | None = None
    for entry in POLICY_TABLE:
        if entry.field_code == field_code:
            table_entry = entry
            break
    # The SEAM_KNOWN_FIELDS frozenset is built from POLICY_TABLE, so if
    # we got past the UnknownFieldError check, table_entry is not None.
    assert table_entry is not None  # nosec - guarded by SEAM_KNOWN_FIELDS
    if table_entry.policy != policy:
        raise InvalidPolicyError(
            f"policy mismatch for field {field_code!r}: caller supplied "
            f"{policy!r} but C7 POLICY_TABLE says {table_entry.policy!r}. "
            f"This is a programmer error; the guard refuses to evaluate."
        )

    # -----------------------------------------------------------------
    # Policy-specific promotion rules (C8 §5.2)
    # -----------------------------------------------------------------

    # Rule 1: frozen fields ALWAYS raise. There is no override.
    # This is the structural hard rule. No flag flip, no future
    # C-phase, no per-project opt-in can enable promotion of
    # frozen fields.
    if policy == POLICY_FROZEN:
        raise PromotionBlockedError(
            f"field {field_code!r} is frozen (structural). "
            f"Frozen fields cannot be promoted by Layer 5. "
            f"This is a hard rule; there is no override. "
            f"See C8 §3.2 and C8 §5.2 row 1."
        )

    # Rule 2: retained fields NEVER raise. The guard is a no-op
    # for retained fields because they are not bridge-sourced;
    # they are manual values that flow through the waterfall
    # unchanged regardless of construction-period state.
    if policy == POLICY_RETAINED:
        # Pass-through. No promotion check needed.
        return None

    # Rule 3: replaced fields raise unless explicitly promoted.
    # The exception is fields subject to R-PAR-2 (currently
    # ``senior_idc_keur``), which require the R-PAR-2 caveat
    # to be resolved or formally accepted in addition to the
    # promotion request.
    if policy == POLICY_REPLACED:
        if field_code in RPAR2_FIELDS:
            # R-PAR-2 blocking constraint. The caller must
            # supply both ``promotion_requested=True`` AND
            # ``rpar2_resolved=True``. The fail-closed default
            # for ``rpar2_resolved`` means C10 cannot promote
            # this field without first resolving R-PAR-2 in a
            # separate workstream.
            if not (promotion_requested and rpar2_resolved):
                raise PromotionBlockedError(
                    f"field {field_code!r} is subject to C1 R-PAR-2 "
                    f"(senior IDC effective-rate caveat). Promotion is "
                    f"blocked until R-PAR-2 is resolved or formally "
                    f"accepted. promotion_requested={promotion_requested}, "
                    f"rpar2_resolved={rpar2_resolved}. "
                    f"See C8 §4.4, C8 §5.2 row 3-4."
                )
            # R-PAR-2 resolved AND promotion requested: pass.
            return None
        # Non-R-PAR-2 replaced field: just needs promotion_requested.
        if not promotion_requested:
            raise PromotionBlockedError(
                f"field {field_code!r} is 'replaced' and requires explicit "
                f"promotion_requested=True. promotion_requested=False. "
                f"See C8 §5.2 row 6."
            )
        # promotion_requested=True: pass.
        return None

    # Rule 4: derived fields raise unless explicitly promoted AND
    # parity_ok. The guard does NOT compute parity; the caller
    # must supply it based on the bridge's BridgeAuditRow.
    if policy == POLICY_DERIVED:
        if not (promotion_requested and parity_ok):
            raise PromotionBlockedError(
                f"field {field_code!r} is 'derived' and requires both "
                f"promotion_requested=True AND parity_ok=True. "
                f"promotion_requested={promotion_requested}, "
                f"parity_ok={parity_ok}. See C8 §5.2 row 9-10."
            )
        # Both flags set: pass.
        return None

    # All branches handled above; this line is unreachable for
    # valid inputs. Keep it as a defensive guardrail.
    raise InvalidPolicyError(  # pragma: no cover
        f"unreachable: policy {policy!r} was not handled by the guard. "
        f"This is a guard implementation bug."
    )


# ---------------------------------------------------------------------------
# Read-only visibility helper (C8 §7.1 bullet 3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConstructionSeamAuditView:
    """Read-only audit view of the construction bridge output.

    This dataclass is a **summary** of the bridge's audit table,
    suitable for surfacing in an audit endpoint, a CLI inspection
    tool, or a test fixture. It is NOT a runtime input; nothing
    in the runtime waterfall reads from this dataclass.

    The dataclass is frozen so the audit view cannot be mutated
    after construction. A future audit endpoint that returns one
    of these is guaranteed not to leak mutable state.

    The fields are intentionally high-level (counts and a sample)
    rather than the full audit table, because the audit endpoint
    (a future C-phase deliverable, not C9) needs a stable schema
    that is independent of bridge-internal column ordering.

    Attributes
    ----------
    field_count:
        Number of fields in the bridge audit table.
    frozen_count:
        Number of fields with ``policy='frozen'``.
    replaced_count:
        Number of fields with ``policy='replaced'``.
    retained_count:
        Number of fields with ``policy='retained'``.
    derived_count:
        Number of fields with ``policy='derived'``.
    parity_ok_count:
        Number of fields whose ``parity`` is ``PARITY_OK``.
    parity_drift_count:
        Number of fields whose ``parity`` is ``PARITY_DRIFT``.
    rpar2_blocked_count:
        Number of fields subject to R-PAR-2 that would be blocked
        by the guard (counted at audit time, not promotion time).
    """

    field_count: int
    frozen_count: int
    replaced_count: int
    retained_count: int
    derived_count: int
    parity_ok_count: int
    parity_drift_count: int
    rpar2_blocked_count: int


def build_construction_seam_audit_view(
    audit_table: Any,
) -> ConstructionSeamAuditView:
    """Build a read-only audit view from a bridge audit table.

    This is the C9 implementation of the "audit-only visibility
    helper" specified in C8 §7.1 bullet 3. It takes a bridge
    ``BridgeAuditRow`` iterable (or any sequence with the same
    per-row interface) and produces a ``ConstructionSeamAuditView``.

    The function is **pure**: it does not mutate the input, does
    not call the construction engine, does not read or write
    any feature flag, and does not produce runtime waterfall
    input. It is a read-side helper.

    Parameters
    ----------
    audit_table:
        An iterable of bridge audit rows. The function reads
        ``.field_code``, ``.policy``, and ``.parity`` attributes
        from each row. The audit table is typically
        ``OpeningBalanceBridgeResult.audit_table`` from C7.

    Returns
    -------
    ConstructionSeamAuditView
        A frozen summary dataclass with field-count and
        parity counters. Safe to serialize to JSON, return from
        an HTTP endpoint, or log.

    Notes
    -----
    The function does NOT raise on unknown policies or parities.
    Unknown values are simply not counted in the per-policy
    buckets. This is intentional: the audit view is a summary,
    not a validator. Validation is the guard's job (see
    ``assert_no_construction_runtime_promotion``).
    """
    field_count = 0
    frozen_count = 0
    replaced_count = 0
    retained_count = 0
    derived_count = 0
    parity_ok_count = 0
    parity_drift_count = 0
    rpar2_blocked_count = 0

    for row in audit_table:
        field_count += 1
        # Per-policy counts
        if row.policy == POLICY_FROZEN:
            frozen_count += 1
        elif row.policy == POLICY_REPLACED:
            replaced_count += 1
        elif row.policy == POLICY_RETAINED:
            retained_count += 1
        elif row.policy == POLICY_DERIVED:
            derived_count += 1

        # Parity counts
        # The bridge uses PARITY_OK / PARITY_DRIFT / PARITY_UNKNOWN /
        # PARITY_NOT_APPLICABLE constants. We avoid importing those
        # constants from the bridge to keep this function independent
        # of the bridge's parity-string evolution; we compare on the
        # string value 'ok' and 'drift' which are stable per C7.
        parity_value = getattr(row, "parity", None)
        if parity_value == "ok":
            parity_ok_count += 1
        elif parity_value == "drift":
            parity_drift_count += 1

        # R-PAR-2 blocked count: any field subject to R-PAR-2 that
        # is in the replaced policy bucket. R-PAR-2 is currently
        # scoped to ``senior_idc_keur`` only; this counting is
        # forward-compatible if R-PAR-2 is extended to other fields
        # in a future C-phase.
        if (
            getattr(row, "field_code", None) in RPAR2_FIELDS
            and row.policy == POLICY_REPLACED
        ):
            rpar2_blocked_count += 1

    return ConstructionSeamAuditView(
        field_count=field_count,
        frozen_count=frozen_count,
        replaced_count=replaced_count,
        retained_count=retained_count,
        derived_count=derived_count,
        parity_ok_count=parity_ok_count,
        parity_drift_count=parity_drift_count,
        rpar2_blocked_count=rpar2_blocked_count,
    )


# ---------------------------------------------------------------------------
# Seam (C8 §7.1 bullet 1, structural skeleton)
# ---------------------------------------------------------------------------


class ConstructionRuntimeSeam:
    """Layer 5 runtime seam skeleton (C9 scaffolding only).

    This class is a **structural skeleton**. It does not connect
    to the waterfall, does not flip feature flags, does not
    call the construction engine, and does not consume bridge
    output. It only:

    - Holds a reference to the C7 POLICY_TABLE (for policy-name
      lookups).
    - Exposes the guard as a method (``assert_no_promotion``) for
      callers that already have a seam instance.
    - Exposes the audit-view builder as a method
      (``build_audit_view``).
    - Records its own version (``SEAM_VERSION``) so callers can
      assert that the seam they are talking to is the C9 seam
      (or later).

    C10/C11 may extend this class to add a real ``promote_field``
    method that calls the guard and then routes the bridge value
    to the waterfall. **C9 does not implement that method.** C9
    is structural scaffolding; the actual promotion path is a
    future deliverable.

    The class is intentionally minimal. It exists so that:

    1. Tests have a stable target to instantiate and exercise
       the guard and audit-view builder.
    2. C10/C11 can extend the class without breaking existing
       tests (the class is open for extension by subclassing).
    3. A future audit endpoint can be wired to
       ``seam.build_audit_view(audit_table)`` without touching
       the waterfall code.

    The class does not have any mutable state in C9. Future
    phases may add state (e.g. a per-project opt-in registry)
    if and only if those phases are designed to do so.
    """

    #: The seam module version. Mirrors ``SEAM_VERSION``.
    VERSION: Final[str] = SEAM_VERSION

    def __init__(self) -> None:
        # No state in C9. The constructor exists for future
        # extension (e.g. C10 may add a per-project opt-in
        # registry, which the constructor would initialize).
        # C9 keeps it empty.
        pass

    def assert_no_promotion(
        self,
        *,
        field_code: str,
        policy: str,
        promotion_requested: bool,
        rpar2_resolved: bool = False,
        parity_ok: bool = False,
    ) -> None:
        """Method-form wrapper around ``assert_no_construction_runtime_promotion``.

        This is the same guard, just callable as a method on a seam
        instance. C10/C11 may prefer method-form calls if they hold
        a seam instance for the project. C9 tests use both forms.
        """
        assert_no_construction_runtime_promotion(
            field_code=field_code,
            policy=policy,
            promotion_requested=promotion_requested,
            rpar2_resolved=rpar2_resolved,
            parity_ok=parity_ok,
        )

    def build_audit_view(
        self,
        audit_table: Any,
    ) -> ConstructionSeamAuditView:
        """Method-form wrapper around ``build_construction_seam_audit_view``.

        See ``build_construction_seam_audit_view`` for the full
        contract. This wrapper exists so a future audit endpoint
        can hold a seam instance and call
        ``seam.build_audit_view(audit_table)`` rather than the
        free function.
        """
        return build_construction_seam_audit_view(audit_table)

    @staticmethod
    def policy_table() -> Mapping[str, str]:
        """Return a read-only mapping of ``field_code -> policy``
        sourced from the C7 POLICY_TABLE.

        This is a convenience accessor for callers (C10/C11) that
        need to look up a field's policy without parsing the full
        ``BridgeFieldPolicy`` dataclass. The returned mapping is
        a fresh dict; mutating it does not affect the bridge.

        Returns
        -------
        dict[str, str]
            A new dict mapping each known field code to its policy
            string. Order matches POLICY_TABLE.
        """
        return {entry.field_code: entry.policy for entry in POLICY_TABLE}
