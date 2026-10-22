"""financial_engine.shl.maturity_authority — OD-R final-state SHL maturity authority contract.

The cash-sweep shareholder-loan maturity predicate (``closing > tolerance + 1e-9`` at the
contractual maturity period, ``SHL_MATURITY_RESIDUAL_FAILS_CLOSED``) is unchanged. This module
only decides WHEN a breach of that predicate is a financial rejection.

Canonical interpretation (default, deployed): every evaluation is authoritative, so a breach in
any SHL schedule raises immediately.

OD-R (Financial Owner decision "Final-State SHL Maturity Authority"): the predicate is
authoritative only on the final converged financing state —

* the final DSCR-only capacity pass and the final funded pass (or the strict re-solve that
  replaced it) of the returned converged G2A evaluation,
* the same passes of the construction-IDC final idempotence verification G2A,
* the final waterfall SHL schedule,

and only once every existing convergence / idempotence validation has succeeded. Breaches in
provisional G2A, construction-IDC or initial-DSRA fixed-point iterations are recorded as
diagnostics. A failed validation always keeps its own error: final authority was never
established for that evaluation.

Authority is carried explicitly:

``ShlMaturityContext``      passed by a fixed-point owner to ``run_senior_debt_model`` and on to
                            ``compute_shareholder_loan_schedules``. ``None`` (the default
                            everywhere) is the canonical fail-closed behaviour.
``G2aShlMaturityEvidence``  one G2A invocation's per-pass evidence, returned to the owner that
                            knows whether that invocation is provisional or final.
``OdrAttempt``              one complete engine evaluation opened by the OD-R policy owner (the
                            initial-DSRA fixed point). Only that owner opens it, with
                            ``odr_attempt``; it is context-local (never process-global), refuses
                            nesting, and is absent in every other Run, thread and worker process,
                            where the canonical behaviour therefore applies.

No numerical value is changed by this contract: a provisional evaluation computes exactly the
schedule a canonical evaluation computes and differs only in not raising this one exception.
"""
from __future__ import annotations

import dataclasses
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum
from typing import Iterator

SHL_MATURITY_ERROR_CODE = "SHL_MATURITY_RESIDUAL_FAILS_CLOSED"

# Release-closed policy selector values (``GenericFinancingPolicy.shl_maturity_authority``).
SHL_MATURITY_POLICY_CANONICAL = "CANONICAL_EVERY_EVALUATION"
SHL_MATURITY_POLICY_OD_R = "OD_R_FINAL_STATE_SHL_MATURITY_V1"
SHL_MATURITY_POLICIES = (SHL_MATURITY_POLICY_CANONICAL, SHL_MATURITY_POLICY_OD_R)


class ShlMaturityAuthority(str, Enum):
    AUTHORITATIVE = "AUTHORITATIVE"
    PROVISIONAL = "PROVISIONAL"


@dataclass(frozen=True)
class ShlMaturityShortfall:
    """One breach of the unchanged cash-sweep maturity predicate (kEUR, exact float)."""

    closing_keur: float
    period_index: int
    tolerance_keur: float


def shl_maturity_residual_error(
    shortfall: ShlMaturityShortfall, *, evidence: str = "",
) -> ValueError:
    """The canonical maturity exception; ``evidence`` is appended only by OD-R final checks."""
    return ValueError(
        f"{SHL_MATURITY_ERROR_CODE}: "
        f"closing balance {shortfall.closing_keur:.12f} kEUR remains at maturity "
        f"period_index={shortfall.period_index}" + evidence
    )


class ShlMaturityLedger:
    """Append-only record of the breaches observed by ONE provisional evaluation."""

    __slots__ = ("_shortfalls",)

    def __init__(self) -> None:
        self._shortfalls: list[ShlMaturityShortfall] = []

    def record(self, shortfall: ShlMaturityShortfall) -> None:
        if not isinstance(shortfall, ShlMaturityShortfall):
            raise TypeError("ShlMaturityLedger records ShlMaturityShortfall only")
        self._shortfalls.append(shortfall)

    @property
    def shortfalls(self) -> tuple[ShlMaturityShortfall, ...]:
        return tuple(self._shortfalls)

    def first(self) -> ShlMaturityShortfall | None:
        """The breach the canonical evaluation would have raised (first in calculation order)."""
        return self._shortfalls[0] if self._shortfalls else None


@dataclass(frozen=True)
class ShlMaturityContext:
    """Explicit authority of one SHL evaluation. PROVISIONAL must name where breaches go."""

    authority: ShlMaturityAuthority
    ledger: ShlMaturityLedger | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.authority, ShlMaturityAuthority):
            raise TypeError("ShlMaturityContext.authority must be ShlMaturityAuthority")
        if self.authority is ShlMaturityAuthority.PROVISIONAL and not isinstance(
            self.ledger, ShlMaturityLedger
        ):
            raise ValueError("a PROVISIONAL SHL maturity context requires a ShlMaturityLedger")

    @property
    def provisional(self) -> bool:
        return self.authority is ShlMaturityAuthority.PROVISIONAL

    @classmethod
    def provisional_pass(cls) -> "ShlMaturityContext":
        return cls(ShlMaturityAuthority.PROVISIONAL, ShlMaturityLedger())


class G2aShlMaturityEvidence:
    """Per-pass maturity evidence of one G2A (derived-SHL / Senior) invocation.

    Filled by ``run_project_financing_model``; classified by the owner that knows whether the
    invocation is provisional (construction seed / superseded outer iteration / non-final DSRA
    attempt) or final (returned converged G2A / idempotence verification G2A).
    """

    __slots__ = ("provisional_passes", "final_passes", "converged")

    def __init__(self) -> None:
        # (pass site, G2A iteration, first breach) for every pass of a non-converging iteration
        self.provisional_passes: list[tuple[str, int, ShlMaturityShortfall | None]] = []
        # (pass site, first breach or None) for the converging iteration, in calculation order
        self.final_passes: list[tuple[str, ShlMaturityShortfall | None]] = []
        self.converged = False

    def record_iteration(
        self, iteration: int, passes: "list[tuple[str, ShlMaturityContext]]", *, final: bool,
    ) -> None:
        if self.converged:
            raise RuntimeError("OD_R_G2A_EVIDENCE_ALREADY_FINAL")
        # The funded pass that a strict re-solve replaced is not the returned state.
        strict = any(site == "STRICT" for site, _ in passes)
        for site, ctx in passes:
            if final and not (strict and site == "FUNDED"):
                self.final_passes.append((site, ctx.ledger.first()))
            else:
                self.provisional_passes.append((site, iteration, ctx.ledger.first()))
        self.converged = final


WATERFALL_FINAL_CHECK = "WATERFALL.FINAL_SHL_SCHEDULE"
FINAL_EVIDENCE_MISSING = "ODR_FINAL_EVIDENCE_MISSING"
FINAL_EVIDENCE_DUPLICATE = "ODR_FINAL_EVIDENCE_DUPLICATE"
FINAL_EVIDENCE_CONTRADICTORY = "ODR_FINAL_EVIDENCE_CONTRADICTORY"
FINAL_EVIDENCE_UNBOUND = "ODR_FINAL_EVIDENCE_UNBOUND"
FINAL_EVIDENCE_UNKNOWN = "ODR_FINAL_EVIDENCE_UNKNOWN"
FINAL_STATE_MISMATCH = "ODR_FINAL_STATE_MISMATCH"
FINALIZATION_REPEATED = "ODR_FINALIZATION_REPEATED"
UNSUPPORTED_FINANCING = "ODR_UNSUPPORTED_FINANCING"
CONSTRUCTION_G2A_ROLES = ("CONSTRUCTION_RETURNED_G2A", "CONSTRUCTION_VERIFICATION_G2A")
TOP_LEVEL_G2A_ROLES = ("G2A",)
KNOWN_G2A_ROLES = frozenset(CONSTRUCTION_G2A_ROLES + TOP_LEVEL_G2A_ROLES)
# Exactly one DSCR-only capacity pass and exactly one funded pass (or the strict re-solve that replaced it).
CAPACITY_SITE = "CAPACITY"
FUNDED_SITES = frozenset({"FUNDED", "STRICT"})


class OdrFinalizationError(RuntimeError):
    """The returned evaluation lacks complete, unambiguous final evidence: never an accepted result."""


@dataclass(frozen=True)
class OdrFinalCheck:
    name: str
    shortfall: ShlMaturityShortfall | None

    @property
    def passed(self) -> bool:
        return self.shortfall is None


# ----------------------------------------------------------------------------------------------- financial state identity

_FIELDS: dict = {}


def _encode(value, out: bytearray) -> None:
    """Deterministic, type-tagged binary encoding (exact IEEE-754 float bits, ordered dataclass fields, sorted mappings).

    Unknown value types fail closed: a state that cannot be identified exactly cannot be authorised.
    """
    import struct
    from datetime import date
    from decimal import Decimal
    from enum import Enum as _Enum

    if value is None:
        out += b"N"
    elif value is True or value is False:
        out += b"T" if value else b"F"
    elif isinstance(value, _Enum):
        out += b"E" + type(value).__qualname__.encode() + b"." + value.name.encode() + b";"
    elif isinstance(value, float):
        out += b"f" + struct.pack(">d", value)
    elif isinstance(value, int):
        text = str(value).encode()
        out += b"i" + len(text).to_bytes(4, "big") + text
    elif isinstance(value, str):
        text = value.encode("utf-8")
        out += b"s" + len(text).to_bytes(4, "big") + text
    elif isinstance(value, (date, Decimal)):
        text = (type(value).__name__ + ":" + str(value)).encode()
        out += b"d" + len(text).to_bytes(4, "big") + text
    elif isinstance(value, (tuple, list)):
        out += b"(" + len(value).to_bytes(4, "big")
        for item in value:
            _encode(item, out)
        out += b")"
    elif isinstance(value, dict):
        items = []
        for key, item in value.items():
            k = bytearray()
            _encode(key, k)
            v = bytearray()
            _encode(item, v)
            items.append((bytes(k), bytes(v)))
        out += b"{" + len(items).to_bytes(4, "big")
        for k, v in sorted(items):
            out += k + v
        out += b"}"
    elif isinstance(value, (set, frozenset)):
        encoded = []
        for item in value:
            b = bytearray()
            _encode(item, b)
            encoded.append(bytes(b))
        out += b"<" + len(encoded).to_bytes(4, "big") + b"".join(sorted(encoded)) + b">"
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        cls = type(value)
        names = _FIELDS.get(cls)
        if names is None:
            names = _FIELDS[cls] = tuple(f.name for f in dataclasses.fields(cls))
        out += b"C" + cls.__qualname__.encode() + b"["
        for name in names:
            out += name.encode() + b"="
            _encode(getattr(value, name), out)
        out += b"]"
    else:
        raise OdrFinalizationError(
            f"{FINAL_EVIDENCE_UNKNOWN}: financial state contains an unidentifiable value of type {type(value).__qualname__}")


# Financing-dependent parts of the final model (operating inputs, provenance and diagnostics text are excluded).
_MODEL_STATE_FIELDS = ("senior_debt", "shareholder_loan", "post_senior_cash", "tax_and_cfads", "cash_dsra", "debt_sizing",
                       "axis_contract")


def financial_state_digest(financing) -> str:
    """Immutable identity of one financing state: every field of the financing result (structure, Senior and SHL principal,
    construction / IDC / funding, DSRA, cash-reserve and financing-income schedules, SHL model input) plus the financing-
    dependent final model schedules (Senior, SHL, post-Senior cash, tax/CFADS, DSRA, debt sizing, axis contract)."""
    import hashlib

    if not dataclasses.is_dataclass(financing) or isinstance(financing, type) or not hasattr(financing, "project_model_result"):
        raise OdrFinalizationError(f"{FINAL_EVIDENCE_UNBOUND}: {type(financing).__qualname__} is not a financing state")
    out = bytearray(b"FINCO-ODR-FINANCIAL-STATE-V1|" + type(financing).__qualname__.encode() + b"|")
    for field in dataclasses.fields(financing):
        if field.name == "project_model_result":
            model = financing.project_model_result
            out += b"project_model_result=C" + type(model).__qualname__.encode() + b"["
            for name in _MODEL_STATE_FIELDS:
                out += name.encode() + b"="
                _encode(getattr(model, name, None), out)
            out += b"]"
            continue
        out += field.name.encode() + b"="
        _encode(getattr(financing, field.name), out)
    return hashlib.sha256(bytes(out)).hexdigest()


# ----------------------------------------------------------------------------------------------- requirements

@dataclass(frozen=True)
class OdrFinalRequirements:
    """Which final checks the RETURNED financial state requires, derived from that state alone (never from evidence)."""

    g2a_roles: tuple[str, ...]
    waterfall_required: bool
    reason: str
    authority: str = "G2A_DEFERRED"


def _shl_liability(financing) -> bool:
    model = financing.project_model_result
    schedule = getattr(model, "shareholder_loan", None)
    balances = () if schedule is None else (
        tuple(schedule.shl_drawdown_keur) + tuple(schedule.shl_opening_keur) + tuple(schedule.shl_closing_keur))
    return financing.derived_shl_cash_principal_keur > 0.0 or any(value > 0.0 for value in balances)


def required_final_checks(result) -> OdrFinalRequirements:
    """Applicability from the actual final financing state, by EXACT financing type (no subclass inheritance).

    * ``ProjectFinancingResult``: the derived-SHL/Senior fixed point defers its passes; with an SHL schedule in the final
      model, construction-IDC results need the returned and the verification G2A, other results the top-level G2A.
    * ``JuniorFinancingResult``: delegated canonical verification - the Junior path never passes a maturity context, so
      every SHL maturity check inside it is the canonical immediate (fail-closed) check; no deferred G2A role exists.
    * ``MultiSeniorFinancingResult``: V1 has no active SHL facility; an SHL liability there is unsupported.
    * Any other type, and a financing result carrying post-evaluation attachments (U2 cash-reserve / distribution
      accounting schedules), is unsupported under OD-R and fails closed.

    SHL liability = positive derived SHL principal or any positive drawdown / opening / closing balance in the final SHL
    schedule (a very small positive amount is a liability).
    """
    from financial_engine.financing.contracts import ProjectFinancingResult
    from financial_engine.financing.junior_debt import JuniorFinancingResult
    from financial_engine.financing.multisenior import MultiSeniorFinancingResult

    financing = result.financing_result
    kind = type(financing)
    if getattr(financing, "cash_reserve_interest_schedules", None) is not None:
        raise OdrFinalizationError(
            f"{UNSUPPORTED_FINANCING}: the returned financing carries post-evaluation U2 cash-reserve schedules; its final "
            "waterfall evidence cannot be bound to the returned state (canonical U2 finding E-4)")
    liability = _shl_liability(financing)
    if kind is ProjectFinancingResult:
        if getattr(financing.project_model_result, "shareholder_loan", None) is None:
            if liability:
                # An SHL liability whose final model carries no SHL schedule has no evaluable deferred G2A pass:
                # structurally inconsistent, never inferred as inapplicable.
                raise OdrFinalizationError(
                    f"{UNSUPPORTED_FINANCING}: positive SHL liability without a final SHL schedule in the model")
            return OdrFinalRequirements((), liability, "no SHL schedule in the final model")
        roles = CONSTRUCTION_G2A_ROLES if financing.construction_financing is not None else TOP_LEVEL_G2A_ROLES
        return OdrFinalRequirements(roles, liability, "derived-SHL/Senior fixed point")
    if kind is JuniorFinancingResult:
        return OdrFinalRequirements((), liability, "Junior: delegated canonical immediate SHL check", "DELEGATED_CANONICAL")
    if kind is MultiSeniorFinancingResult and not liability:
        return OdrFinalRequirements((), False, "Multi-senior V1: no SHL facility", "NO_SHL_FACILITY")
    raise OdrFinalizationError(
        f"{UNSUPPORTED_FINANCING}: {kind.__module__}.{kind.__qualname__} (shl_liability={liability}) has no OD-R "
        "finalization authority")


# ----------------------------------------------------------------------------------------------- evidence

@dataclass(frozen=True)
class _G2aRegistration:
    role: str
    sites: tuple[tuple[str, ShlMaturityShortfall | None], ...]
    state: str                  # financial_state_digest of the financing the passes produced


@dataclass(frozen=True)
class _WaterfallRegistration:
    state: str                  # financial_state_digest of the financing the waterfall evaluated
    inputs: str                 # digest of the SHL model input and the gated cash vector actually used
    maturity_period_index: int
    repayment_mode: str
    rows: tuple[tuple[int, bytes, bytes, bytes], ...]  # (period, closing, gross, principal) as exact binary64, <= maturity
    shortfall: ShlMaturityShortfall | None


def _bits(value) -> bytes:
    """Exact IEEE-754 binary64 identity (+0.0 and -0.0 differ; no tolerance)."""
    import struct
    return struct.pack(">d", value)


def _digest_of(*values) -> str:
    import hashlib
    out = bytearray(b"FINCO-ODR-WATERFALL-INPUT-V1|")
    for value in values:
        _encode(value, out)
    return hashlib.sha256(bytes(out)).hexdigest()


class OdrAttempt:
    """Maturity evidence of ONE complete engine evaluation under OD-R.

    Every final check is bound to the immutable identity of the financing state it validated (``financial_state_digest``)
    and carries a proof token (the evidence object of the evaluation that produced it). ``finalize`` accepts only evidence
    whose state identity equals the identity of the financing actually returned, recomputed at finalization; evidence of
    other states (superseded U2 / G2A / DSRA evaluations) is diagnostic only.
    """

    def __init__(self) -> None:
        self.provisional_violations: list[tuple[str, ShlMaturityShortfall]] = []
        self.final_checks: list[OdrFinalCheck] = []
        self._g2a: list[_G2aRegistration] = []
        self._waterfall: list[_WaterfallRegistration] = []
        self._tokens: list = []                 # strong references: a proof token can never be recycled in an attempt
        self._registered_states: list = []      # (state object, digest at its first registration) - kept alive
        self._finalized = False

    def _registration_digest(self, state) -> str:
        """Digest of ``state`` at registration (computed once per object in this attempt). ``finalize`` always recomputes the
        returned state's digest, so a mutation after registration can never match."""
        for existing, digest in self._registered_states:
            if existing is state:
                return digest
        digest = financial_state_digest(state)
        self._registered_states.append((state, digest))
        return digest

    def _register_token(self, token) -> None:
        if self._finalized:
            raise OdrFinalizationError(f"{FINALIZATION_REPEATED}: evidence after finalization")
        if any(existing is token for existing in self._tokens):
            raise OdrFinalizationError(f"{FINAL_EVIDENCE_DUPLICATE}: one evaluation registered twice")
        self._tokens.append(token)

    def absorb_g2a(self, evidence: G2aShlMaturityEvidence, *, final: bool, role: str, state=None) -> None:
        """``state`` is the financing result the converged passes produced (final evidence only)."""
        if not isinstance(evidence, G2aShlMaturityEvidence):
            raise TypeError("OdrAttempt absorbs G2aShlMaturityEvidence only")
        if role not in KNOWN_G2A_ROLES and final:
            raise OdrFinalizationError(f"{FINAL_EVIDENCE_UNKNOWN}: G2A role {role!r}")
        for site, iteration, shortfall in evidence.provisional_passes:
            if shortfall is not None:
                self.provisional_violations.append((f"{role}.ITER{iteration}.{site}", shortfall))
        if final:
            if not evidence.converged:
                raise RuntimeError(f"OD_R_FINAL_G2A_EVIDENCE_INCOMPLETE: {role}")
            if state is None:
                raise OdrFinalizationError(f"{FINAL_EVIDENCE_UNBOUND}: final evidence must name its evaluated state")
            self._register_token(evidence)
            self._g2a.append(_G2aRegistration(role, tuple(evidence.final_passes), self._registration_digest(state)))
        else:
            for site, shortfall in evidence.final_passes:
                if shortfall is not None:
                    self.provisional_violations.append((f"{role}.CONVERGED.{site}", shortfall))

    def record_final_waterfall(self, context, *, financing=None, shl_input=None, cash=None, schedule=None) -> None:
        """The waterfall SHL schedule check for ``financing``: ``context`` is the maturity context the kernel evaluated
        (proof token and breach ledger); ``shl_input`` / ``cash`` are the exact inputs; ``schedule`` the schedule it produced."""
        if not isinstance(context, ShlMaturityContext) or not context.provisional:
            raise OdrFinalizationError(f"{FINAL_EVIDENCE_UNBOUND}: waterfall evidence needs the evaluated maturity context")
        if financing is None or shl_input is None or cash is None or schedule is None:
            raise OdrFinalizationError(f"{FINAL_EVIDENCE_UNBOUND}: waterfall evidence must name state, inputs and schedule")
        self._register_token(context)
        vectors = (tuple(schedule.period_indices), tuple(schedule.shl_closing_keur),
                   tuple(schedule.shl_gross_interest_keur), tuple(schedule.shl_principal_keur))
        indices = vectors[0]
        if (len({len(vector) for vector in vectors}) != 1 or not indices
                or any(type(index) is not int for index in indices)
                or any(b <= a for a, b in zip(indices, indices[1:]))
                or any(not isinstance(value, float) for vector in vectors[1:] for value in vector)):
            raise OdrFinalizationError(
                f"{FINAL_EVIDENCE_CONTRADICTORY}: waterfall SHL schedule vectors are misaligned, unordered or duplicated")
        rows = tuple(
            (index, _bits(closing), _bits(gross), _bits(principal))
            for index, closing, gross, principal in zip(*vectors)
            if index <= shl_input.maturity_period_index)
        self._waterfall.append(_WaterfallRegistration(
            self._registration_digest(financing), _digest_of(shl_input, tuple(cash)), shl_input.maturity_period_index,
            getattr(shl_input.repayment_mode, "name", str(shl_input.repayment_mode)), rows, context.ledger.first()))

    def demote(self, role: str) -> None:
        """This whole evaluation was superseded (non-final DSRA iteration): all of it is provisional."""
        for registration in self._g2a:
            for site, shortfall in registration.sites:
                if shortfall is not None:
                    self.provisional_violations.append((f"{role}.{registration.role}.FINAL_{site}", shortfall))
        for registration in self._waterfall:
            if registration.shortfall is not None:
                self.provisional_violations.append((f"{role}.{WATERFALL_FINAL_CHECK}", registration.shortfall))
        self._g2a, self._waterfall, self.final_checks = [], [], []

    def finalize(self, result) -> OdrFinalRequirements:
        """Decide the returned evaluation exactly once, before it can be returned.

        Order: unsupported financing / unidentifiable state; economic breach at a required final check (canonical maturity
        error); contradictory or unknown evidence; missing evidence. Absence of evidence never establishes inapplicability.
        """
        if self._finalized:
            raise OdrFinalizationError(f"{FINALIZATION_REPEATED}: an evaluation is finalized once")
        self._finalized = True
        requirements = required_final_checks(result)
        financing = result.financing_result
        state = financial_state_digest(financing)
        checks: list[OdrFinalCheck] = []
        missing: list[str] = []
        contradictory: list[str] = []

        returned_g2a = [r for r in self._g2a if r.state == state]
        for registration in self._g2a:
            if registration.state != state:
                for site, shortfall in registration.sites:
                    if shortfall is not None:
                        self.provisional_violations.append((f"SUPERSEDED.{registration.role}.FINAL_{site}", shortfall))
        for registration in returned_g2a:
            if registration.sites and registration.role not in requirements.g2a_roles:
                contradictory.append(f"{registration.role} evaluated SHL passes for a state that requires none")
        for role in requirements.g2a_roles:
            registrations = [r for r in returned_g2a if r.role == role]
            if not registrations:
                missing += [f"{role}.FINAL_CAPACITY", f"{role}.FINAL_FUNDED_OR_STRICT"]
                continue
            if len(registrations) != 1:
                # Exactly one authoritative final evaluation per role: separate tokens are not separate checks.
                contradictory.append(f"{role} registered {len(registrations)} times for the returned state")
            for registration in registrations:
                sites = [site for site, _ in registration.sites]
                unknown = [site for site in sites if site != CAPACITY_SITE and site not in FUNDED_SITES]
                if unknown:
                    contradictory.append(f"{role} unknown site(s) {sorted(unknown)}")
                if sites.count(CAPACITY_SITE) != 1:
                    (missing if CAPACITY_SITE not in sites else contradictory).append(f"{role}.FINAL_CAPACITY")
                funded = [site for site in sites if site in FUNDED_SITES]
                if len(funded) != 1:
                    (missing if not funded else contradictory).append(f"{role}.FINAL_FUNDED_OR_STRICT")
                checks += [OdrFinalCheck(f"{role}.FINAL_{site}", shortfall) for site, shortfall in registration.sites]

        returned_rows, operating, axis, returned_maturity, row_problem = self._returned_rows(result)
        if row_problem and requirements.waterfall_required:
            contradictory.append(row_problem)
        bound = [r for r in self._waterfall if r.state == state]
        for registration in self._waterfall:
            if registration.state != state and registration.shortfall is not None:
                self.provisional_violations.append((f"SUPERSEDED.{WATERFALL_FINAL_CHECK}", registration.shortfall))
        matching = [r for r in bound if not row_problem
                    and self._rows_match(r, returned_rows, operating, axis, returned_maturity)]
        for registration in bound:
            if registration not in matching and registration.shortfall is not None:
                self.provisional_violations.append((f"STALE.{WATERFALL_FINAL_CHECK}", registration.shortfall))
        if requirements.waterfall_required:
            if not matching:
                missing.append(WATERFALL_FINAL_CHECK + (
                    " (no check evaluated the returned SHL schedule)" if bound else ""))
            elif len({(r.inputs, r.rows, r.shortfall) for r in matching}) != 1:
                contradictory.append(f"{WATERFALL_FINAL_CHECK} evaluated with different inputs for one returned schedule")
            # Legitimate repeats of the identical evaluation collapse to one check; any breach is decisive.
            checks += [OdrFinalCheck(WATERFALL_FINAL_CHECK, shortfall)
                       for shortfall in sorted({r.shortfall for r in matching}, key=lambda s: s is None)]
        elif bound:
            contradictory.append(f"{WATERFALL_FINAL_CHECK} recorded for a state without SHL liability")

        self.final_checks = checks
        error = self.final_failure_error()
        if error is not None:
            raise error
        if contradictory:
            raise OdrFinalizationError(f"{FINAL_EVIDENCE_CONTRADICTORY}: {'; '.join(contradictory)}")
        if missing:
            raise OdrFinalizationError(
                f"{FINAL_EVIDENCE_MISSING}: {', '.join(missing)} (required by the returned state: {requirements.reason}; "
                f"shl_liability={requirements.waterfall_required})")
        return requirements

    @staticmethod
    def _returned_rows(result):
        """Returned operating SHL rows in their ORIGINAL order as (period, closing, gross, principal) exact binary64, plus the
        operating period set, the model period axis (model order) and the returned contractual SHL maturity.

        Construction rows carry their own construction numbering (they may share an index with an operating period) and are
        excluded by their ``is_construction`` flag. Every non-construction row must be an operating model period: an extra,
        off-axis or duplicated operating row is a defect, never filtered, collapsed or re-sorted."""
        periods = getattr(result, "waterfall_periods", None)
        model_periods = getattr(result.financing_result.project_model_result, "periods", None)
        terminal = getattr(getattr(getattr(result, "return_summary", None), "terminal", None), "shareholder_loan", None)
        maturity = getattr(terminal, "contractual_maturity_period_index", None)
        if periods is None or model_periods is None:
            return (), frozenset(), (), maturity, "returned result carries no waterfall periods"
        axis = tuple(p.period_index for p in model_periods)
        operating = frozenset(p.period_index for p in model_periods if getattr(p, "is_operation", False))
        operating_order = tuple(index for index in axis if index in operating)
        rows = []
        for row in periods:
            if row.is_construction:
                continue
            if row.period_index not in operating:
                return (), operating, axis, maturity, (
                    f"returned waterfall row {row.period_index} is not an operating model period")
            rows.append((row.period_index, _bits(row.shl_closing_balance_keur), _bits(row.shl_gross_interest_keur),
                         _bits(row.actual_shl_principal_paid_keur)))
        order = tuple(row[0] for row in rows)
        if len(set(order)) != len(order):
            duplicated = next(index for index in order if order.count(index) > 1)
            return (), operating, axis, maturity, f"returned waterfall duplicates SHL period {duplicated}"
        if order != operating_order:
            return (), operating, axis, maturity, "returned operating waterfall rows are missing, extra or out of model order"
        return tuple(rows), operating, axis, maturity, None

    @staticmethod
    def _rows_match(registration: _WaterfallRegistration, returned: tuple, operating: frozenset, axis: tuple,
                    maturity) -> bool:
        """The checked schedule covers exactly the model period axis up to the returned contractual SHL maturity (model
        order, no off-axis period), and every returned operating row up to that maturity is bit-identical to it."""
        if maturity is None or registration.maturity_period_index != maturity or maturity not in operating:
            return False
        scope = tuple(index for index in axis if index <= maturity)
        if tuple(row[0] for row in registration.rows) != scope:
            return False
        checked = {row[0]: row[1:] for row in registration.rows if row[0] in operating}
        in_scope = tuple(row for row in returned if row[0] <= maturity)
        if tuple(row[0] for row in in_scope) != tuple(index for index in scope if index in operating):
            return False
        return all(checked[row[0]] == row[1:] for row in in_scope)

    def first_final_failure(self) -> OdrFinalCheck | None:
        return next((c for c in self.final_checks if not c.passed), None)

    def final_failure_error(self) -> ValueError | None:
        failure = self.first_final_failure()
        if failure is None:
            return None
        return shl_maturity_residual_error(
            failure.shortfall,
            evidence=(
                f"; od_r_final_check={failure.name}"
                f"; od_r_failed_final_checks={sum(not c.passed for c in self.final_checks)}"
                f"; od_r_provisional_violations={len(self.provisional_violations)}"
            ),
        )


@dataclass(frozen=True)
class OdrMaturityEvidence:
    """Bounded, deterministic OD-R decision-path evidence attached to an accepted result."""

    authority: str
    provisional_violation_count: int
    max_provisional_shortfall_keur: float
    final_checks_performed: tuple[str, ...]
    final_waterfall_check: str
    superseded_attempts: int

    def to_metadata(self) -> dict:
        return {
            "shl_maturity_authority": self.authority,
            "shl_maturity_provisional_violations": self.provisional_violation_count,
            "shl_maturity_max_provisional_shortfall_keur": self.max_provisional_shortfall_keur,
            "shl_maturity_final_checks": list(self.final_checks_performed),
            "shl_maturity_final_waterfall_check": self.final_waterfall_check,
            "shl_maturity_superseded_dsra_attempts": self.superseded_attempts,
        }


def summarize(final: OdrAttempt, superseded: "list[OdrAttempt]",
              requirements: OdrFinalRequirements) -> OdrMaturityEvidence:
    """Evidence of a FINALIZED, accepted evaluation. The waterfall label follows the established applicability."""
    if not final._finalized or final.first_final_failure() is not None:
        raise RuntimeError("OD_R_EVIDENCE_REQUESTED_FOR_UNFINALIZED_OR_REJECTED_STATE")
    provisional = [s for a in superseded for _, s in a.provisional_violations]
    provisional += [s for _, s in final.provisional_violations]
    return OdrMaturityEvidence(
        authority=SHL_MATURITY_POLICY_OD_R,
        provisional_violation_count=len(provisional),
        max_provisional_shortfall_keur=max((s.closing_keur for s in provisional), default=0.0),
        final_checks_performed=tuple(c.name for c in final.final_checks),
        final_waterfall_check="PASSED" if requirements.waterfall_required else "NOT_APPLICABLE_NO_SHL",
        superseded_attempts=len(superseded),
    )


_ATTEMPT: ContextVar[OdrAttempt | None] = ContextVar("finco_od_r_attempt", default=None)


def current_attempt() -> OdrAttempt | None:
    """The OD-R evaluation open in this context, or None (canonical behaviour)."""
    return _ATTEMPT.get()


@contextmanager
def odr_attempt(attempt: OdrAttempt) -> Iterator[OdrAttempt]:
    """Open one OD-R engine evaluation.

    Final authority exists only for an evaluation that completed every required convergence,
    funding and idempotence validation (and, at the policy owner, the initial-DSRA fixed point).
    An evaluation that raised never established that authority, so any exception escaping it
    propagates unchanged; recorded breaches are never substituted for it. Final breaches are
    enforced only by the owner, on the returned evaluation, before the result is returned.
    """
    if not isinstance(attempt, OdrAttempt):
        raise TypeError("odr_attempt requires an OdrAttempt")
    if _ATTEMPT.get() is not None:
        raise RuntimeError("OD_R_ATTEMPT_NESTING_REFUSED")
    token = _ATTEMPT.set(attempt)
    try:
        yield attempt
    finally:
        _ATTEMPT.reset(token)


__all__ = [
    "SHL_MATURITY_ERROR_CODE", "SHL_MATURITY_POLICY_CANONICAL", "SHL_MATURITY_POLICY_OD_R",
    "SHL_MATURITY_POLICIES", "ShlMaturityAuthority", "ShlMaturityShortfall",
    "ShlMaturityLedger", "ShlMaturityContext", "shl_maturity_residual_error",
    "G2aShlMaturityEvidence", "WATERFALL_FINAL_CHECK", "OdrFinalCheck", "OdrFinalRequirements",
    "OdrFinalizationError", "required_final_checks", "financial_state_digest", "OdrAttempt", "OdrMaturityEvidence",
    "summarize", "current_attempt", "odr_attempt",
]
