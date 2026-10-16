"""Canonical freshness authority for persisted Workbook V2 runtime evidence.

Freshness is a presentation/audit decision only.  It never runs the engine or
derives economics.  Modern workspaces compare the current composite workbook
identity with the identity committed by the last Run; legacy workspaces retain
the pre-composite scalar/dirty fallback.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class RuntimeAuthorityState(str, Enum):
    NOT_RUN = "NOT_RUN"
    CURRENT = "CURRENT"
    STALE = "STALE"


@dataclass(frozen=True)
class RuntimeFreshness:
    has_runtime: bool
    is_stale: bool
    state: RuntimeAuthorityState
    current_composite_hash: Optional[str]
    last_runtime_composite_hash: Optional[str]
    source: str


def pre_scenario_base_equivalent(
    cursor: Any,
    *,
    draft_snapshot_json: str,
    project_id: str,
    user_id: str,
    scenario: Any,
    last_runtime_scenario_id: Optional[str],
    last_hash: Optional[str],
) -> bool:
    """Narrow Base compatibility rule for runs committed before scenarios existed.

    The canonical identity defines ``scenario_id=None`` as the Base Case. A Base
    run committed before the Base scenario row existed therefore carries a
    composite hash computed under that None convention, while the explicit Base
    row hashes with its own id. Presentation/freshness may treat the two as the
    same state ONLY when ALL hold, positively proven:

      * ``scenario`` is the canonical Base Case,
      * the Base Case has no economic overrides,
      * the run recorded no scenario id (pre-scenario),
      * recomputing the identity under the None convention reproduces the
        run's original composite hash exactly.

    Pure freshness decision: nothing about the run's provenance is rewritten.
    No non-Base scenario can ever satisfy this. Any error fails closed (False).
    """
    try:
        if (scenario is None or not getattr(scenario, "is_base_case", False)
                or getattr(scenario, "overrides", None)
                or last_runtime_scenario_id or not last_hash):
            return False
        from app.workbook.registry import WORKBOOK
        from app.workbook.workbook_identity import assemble_transactional

        legacy = assemble_transactional(
            draft_snapshot_json=draft_snapshot_json,
            project_id=project_id, user_id=user_id,
            active_scenario_id=None, active_scenario_name=None,
            cursor=cursor, workbook_version=WORKBOOK.version,
        )
        return legacy.composite_hash == last_hash
    except Exception:
        return False


def resolve_runtime_freshness(
    ws: Any,
    *,
    current_composite_hash: Optional[str],
) -> RuntimeFreshness:
    """Resolve whether persisted Last Run evidence matches current inputs.

    A missing current hash on a modern row is fail-closed: Current cannot be
    proven, so the persisted result is classified STALE.
    """
    has_runtime = bool(
        getattr(ws, "last_runtime_snapshot_id", None)
        or (
            getattr(ws, "any_run_committed", False)
            and getattr(ws, "last_runtime_snapshot", None)
        )
    )
    last_hash = getattr(ws, "last_runtime_composite_hash", None) or None
    if not has_runtime:
        return RuntimeFreshness(
            False, False, RuntimeAuthorityState.NOT_RUN,
            current_composite_hash, last_hash, "no_runtime",
        )

    if last_hash:
        stale = not current_composite_hash or current_composite_hash != last_hash
        if stale and current_composite_hash and _base_equivalence_holds(ws, last_hash) \
                and not _opex_fold_superseded(ws):
            return RuntimeFreshness(
                True, False, RuntimeAuthorityState.CURRENT,
                current_composite_hash, last_hash, "pre_scenario_base_equivalence",
            )
        if not stale and _opex_fold_superseded(ws):
            # Same inputs, but the Run was computed under an OPEX fold that has
            # since been corrected: a new Run would calculate different economics.
            return RuntimeFreshness(
                True, True, RuntimeAuthorityState.STALE,
                current_composite_hash, last_hash, "opex_fold_semantics_superseded",
            )
        return RuntimeFreshness(
            True, stale,
            RuntimeAuthorityState.STALE if stale else RuntimeAuthorityState.CURRENT,
            current_composite_hash, last_hash,
            "composite_hash" if current_composite_hash else "identity_unresolved",
        )

    # Legacy rows predate run-bound composite identity.  Preserve their scalar
    # snapshot/dirty behavior without allowing it to affect the modern path.
    from app.persistence._helpers import snapshots_equal

    stale = bool(getattr(ws, "dirty", False)) or not snapshots_equal(
        getattr(ws, "draft_snapshot", None) or {},
        getattr(ws, "last_runtime_snapshot", None) or {},
    )
    return RuntimeFreshness(
        True, stale,
        RuntimeAuthorityState.STALE if stale else RuntimeAuthorityState.CURRENT,
        current_composite_hash, None, "legacy_scalar_fallback",
    )


def _opex_fold_superseded(ws: Any) -> bool:
    """Run committed under the superseded OPEX fold on a project it affects."""
    identity = getattr(ws, "last_runtime_identity", None)
    if not isinstance(identity, dict):
        return False
    from app.services.opex_sub_lines_integration import run_predates_opex_seed_replacement

    return run_predates_opex_seed_replacement(getattr(ws, "project_id", None), identity)


def _base_equivalence_holds(ws: Any, last_hash: str) -> bool:
    """Evaluate :func:`pre_scenario_base_equivalent` for a persisted workspace."""
    try:
        if getattr(ws, "last_runtime_scenario_id", None):
            return False
        scenario_id = getattr(ws, "active_scenario_id", None)
        user_id = getattr(ws, "user_id", None)
        project_id = getattr(ws, "project_id", None)
        if not (scenario_id and user_id and project_id):
            return False
        import json

        from app.persistence.db import get_cursor
        from app.persistence.scenarios_repository import get_scenario

        scenario = get_scenario(scenario_id, user_id)
        with get_cursor() as cur:
            return pre_scenario_base_equivalent(
                cur,
                draft_snapshot_json=json.dumps(getattr(ws, "draft_snapshot", None) or {}),
                project_id=project_id, user_id=user_id, scenario=scenario,
                last_runtime_scenario_id=None, last_hash=last_hash,
            )
    except Exception:
        return False


# ───────────────────────────── independent Run status dimensions (SC-03) ─────────────────────────────
# "CURRENT" above is INPUT FRESHNESS only: the composite input identity of the Run equals the Working Copy's.  It says
# nothing about the engine that produced the Run or about the Run's Integrity verdict.  The dimensions below are
# additive and independent; none of them is derived from another and none rewrites a persisted Run.

class EngineCurrency(str, Enum):
    CURRENT_ENGINE = "CURRENT_ENGINE"
    ENGINE_SUPERSEDED = "ENGINE_SUPERSEDED"
    ENGINE_IDENTITY_UNKNOWN = "ENGINE_IDENTITY_UNKNOWN"


class RunContext(str, Enum):
    LAST_RUN = "LAST_RUN"
    HISTORICAL_RUN = "HISTORICAL_RUN"


#: D2 (owner decision pending): how a proven ENGINE_SUPERSEDED Run is treated in the product (badge wording, banner,
#: re-run call to action).  Until accepted, the evidence is computed and exposed as data attributes only and no
#: governed user-facing treatment is rendered.
ENGINE_SUPERSEDED_GOVERNED_DISPLAY_ENABLED = False

_UNKNOWN_ENGINE_TOKENS = frozenset({"", "NOT_AVAILABLE", "UNKNOWN", "NONE", "NULL", "N/A"})


@dataclass(frozen=True)
class EngineCurrencyEvidence:
    state: EngineCurrency
    persisted_engine_version: Optional[str]
    current_engine_version: Optional[str]
    source: str          # which persisted field supplied the identity, or why none could
    reason: str


def current_engine_version() -> str:
    from financial_engine.version import ENGINE_VERSION
    return str(ENGINE_VERSION)


def _clean_engine_token(value: Any) -> Optional[str]:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return None if text.upper() in _UNKNOWN_ENGINE_TOKENS else text


def persisted_engine_identity(*, identity: Any = None, replay_metadata: Any = None,
                              history_engine_version: Any = None) -> tuple[Optional[str], str, str]:
    """(engine_version, source, reason) read ONLY from what the Run itself committed.

    Never inferred from timestamps, deployment versions or the current engine.  Two committed values that disagree make
    the identity ambiguous, which is reported as unknown (fail closed) rather than choosing one.
    """
    candidates = []
    if isinstance(identity, dict):
        candidates.append(("last_runtime_identity.engine_version", _clean_engine_token(identity.get("engine_version"))))
    if isinstance(replay_metadata, dict):
        candidates.append(("replay_metadata.engine_version", _clean_engine_token(replay_metadata.get("engine_version"))))
    candidates.append(("run_history.engine_version", _clean_engine_token(history_engine_version)))
    present = [(src, val) for src, val in candidates if val]
    if not present:
        return None, "none_persisted", "NO_ENGINE_IDENTITY_PERSISTED"
    values = {val for _src, val in present}
    if len(values) > 1:
        return None, "conflicting_persisted_values", "CONFLICTING_PERSISTED_ENGINE_IDENTITY"
    return present[0][1], present[0][0], "PERSISTED_ENGINE_IDENTITY"


def resolve_engine_currency(*, identity: Any = None, replay_metadata: Any = None, history_engine_version: Any = None,
                            current: Optional[str] = None) -> EngineCurrencyEvidence:
    """CURRENT_ENGINE only when a persisted identity equals the running engine's declared version; ENGINE_SUPERSEDED only
    when a persisted identity is known and differs; otherwise ENGINE_IDENTITY_UNKNOWN.

    The engine version is the product's declared engine identity.  Equality establishes that the Run was produced under
    the same declared engine version; it is not a proof that no code changed without a version bump.
    """
    now = _clean_engine_token(current) if current is not None else _clean_engine_token(current_engine_version())
    persisted, source, reason = persisted_engine_identity(
        identity=identity, replay_metadata=replay_metadata, history_engine_version=history_engine_version)
    if persisted is None or now is None:
        return EngineCurrencyEvidence(EngineCurrency.ENGINE_IDENTITY_UNKNOWN, persisted, now, source,
                                      reason if persisted is None else "CURRENT_ENGINE_IDENTITY_UNAVAILABLE")
    state = EngineCurrency.CURRENT_ENGINE if persisted == now else EngineCurrency.ENGINE_SUPERSEDED
    return EngineCurrencyEvidence(state, persisted, now, source, reason)


@dataclass(frozen=True)
class RunStatusDimensions:
    """Four independent facts about the displayed Run; none implies another."""
    run_context: RunContext
    input_freshness: Optional[str]       # NOT_RUN / CURRENT / STALE; None when it was not evaluated
    engine: EngineCurrencyEvidence
    integrity: str                       # PASS / FAIL / INCOMPLETE / UNAVAILABLE (existing precise statuses)
    input_freshness_basis: str           # what "input freshness" was compared against

    def to_dict(self) -> dict:
        return {
            "run_context": self.run_context.value,
            "input_freshness": self.input_freshness,
            "input_freshness_basis": self.input_freshness_basis,
            "engine_currency": self.engine.state.value,
            "engine_persisted_version": self.engine.persisted_engine_version,
            "engine_current_version": self.engine.current_engine_version,
            "engine_identity_source": self.engine.source,
            "engine_reason": self.engine.reason,
            "integrity": self.integrity,
            "engine_superseded_treatment": ("GOVERNED" if ENGINE_SUPERSEDED_GOVERNED_DISPLAY_ENABLED else "EVIDENCE_ONLY_D2_PENDING"),
        }


def resolve_run_status_dimensions(*, run_context: RunContext, input_freshness: Optional[str], integrity: Optional[str],
                                  identity: Any = None, replay_metadata: Any = None,
                                  history_engine_version: Any = None, current_engine: Optional[str] = None,
                                  input_freshness_basis: Optional[str] = None) -> RunStatusDimensions:
    state = str(input_freshness).upper() if input_freshness else None
    if state not in (None, "NOT_RUN", "CURRENT", "STALE"):
        state = None
    status = str(integrity or "").upper()
    if status not in ("PASS", "FAIL", "INCOMPLETE", "UNAVAILABLE"):
        status = "UNAVAILABLE"
    basis = input_freshness_basis or ("current Working Copy composite input identity" if state else "not evaluated")
    return RunStatusDimensions(
        run_context=run_context, input_freshness=state, integrity=status, input_freshness_basis=basis,
        engine=resolve_engine_currency(identity=identity, replay_metadata=replay_metadata,
                                       history_engine_version=history_engine_version, current=current_engine))
