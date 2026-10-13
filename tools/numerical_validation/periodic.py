"""F3.9 structured period-by-period reconciliation (validation only, NOT a financial engine).

Builds on the P0-B3 framework (same states, same dependency stages, same Decimal discipline, same deterministic
JSON/CSV/Markdown reports) and adds what a single committed Run needs:

* a typed **tolerance policy** whose approved value and origin are explicit, never widened per case;
* a **representation allowance** for values persisted at 2 decimal places, kept separate from the financial tolerance;
* exact **period alignment** by a typed period key, with duplicate / missing / unprovable axes reported, not repaired;
* relative **and** absolute residuals, signed ``observed - expected``;
* the **earliest divergence in financial dependency order**, and a separation of input mismatches from calculation
  mismatches and from differences that merely sit downstream of an earlier one.

Importing this module imports no FINCO production module and runs no model.  A PASS says only that one declared
identity holds within its declared allowance; it is not a finding that the engine or the assumptions are correct.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable

from .reconcile import CATEGORIES, STATES, ReconciliationInputError, _str, canonical_bytes

SCHEMA = "FINCO_NUMERICAL_RECONCILIATION_V1"
QUANTUM_2DP = Decimal("0.01")

# Outcome kinds: what a failing identity would mean.
KIND_INPUT = "INPUT_RECORD"            # a recorded assumption / axis is inconsistent with independent evidence
KIND_CALCULATION = "CALCULATION"       # outputs are inconsistent with the independent recomputation of the same inputs
KINDS = (KIND_INPUT, KIND_CALCULATION)

CLASS_INPUT = "INPUT_MISMATCH"
CLASS_CALCULATION = "CALCULATION_MISMATCH"
CLASS_DOWNSTREAM = "DOWNSTREAM_OF_EARLIER_DIVERGENCE"

BASIS_FULL = "FULL_PRECISION"
BASIS_2DP = "PERSISTED_2DP"
BASES = (BASIS_FULL, BASIS_2DP)


@dataclass(frozen=True)
class TolerancePolicy:
    """An approved allowance, with where it comes from and why it applies.  Never adjusted per identity."""

    key: str
    abs_tolerance: Decimal
    rel_tolerance: Decimal
    origin: str
    justification: str

    def __post_init__(self):
        if self.abs_tolerance < 0 or self.rel_tolerance < 0:
            raise ReconciliationInputError(f"tolerance {self.key}: negative allowance")
        if not self.origin.strip() or not self.justification.strip():
            raise ReconciliationInputError(f"tolerance {self.key}: origin and justification are required")


def representation_allowance(rounded_terms: int, quantum: Decimal = QUANTUM_2DP) -> Decimal:
    """Largest possible difference caused by serialising ``rounded_terms`` values to ``quantum``.

    A value rounded to 2 decimals can be wrong by at most half a quantum; a sum of such terms by the sum of those
    bounds.  This is a bound on REPRESENTATION, applied only to values the product itself persists rounded, and it is
    reported separately from the approved financial tolerance.
    """
    if rounded_terms < 0:
        raise ReconciliationInputError("rounded_terms must not be negative")
    return quantum / 2 * rounded_terms


@dataclass(frozen=True)
class Outcome:
    identity: str
    stage: str
    period: str | None
    status: str
    reason: str
    kind: str
    basis: str
    tolerance_policy: str
    observed: Decimal | None = None
    expected: Decimal | None = None
    residual: Decimal | None = None
    abs_residual: Decimal | None = None
    rel_residual: Decimal | None = None
    allowance: Decimal | None = None
    representation_allowance: Decimal | None = None
    classification: str = ""


@dataclass(frozen=True)
class IdentityInfo:
    """What an identity is, so a report can state what was and was not verified."""

    key: str
    stage: str
    kind: str
    title: str
    basis: str
    tolerance_policy: str


class Reconciler:
    """Collects outcomes; every identity is registered once and every evaluation is explicit."""

    def __init__(self, policies: Iterable[TolerancePolicy], *, identity: dict[str, Any] | None = None):
        self.policies = {p.key: p for p in policies}
        if not self.policies:
            raise ReconciliationInputError("at least one tolerance policy is required")
        self.identity = dict(identity or {})
        self._registry: dict[str, IdentityInfo] = {}
        self._outcomes: list[Outcome] = []
        self._seen: set[tuple[str, str | None]] = set()

    # ── registration ──────────────────────────────────────────────────────────────────────────────
    def register(self, key: str, stage: str, kind: str, title: str, basis: str, policy: str) -> IdentityInfo:
        if stage not in CATEGORIES:
            raise ReconciliationInputError(f"identity {key}: unsupported dependency stage {stage!r}")
        if kind not in KINDS or basis not in BASES:
            raise ReconciliationInputError(f"identity {key}: unsupported kind or basis")
        if policy not in self.policies:
            raise ReconciliationInputError(f"identity {key}: unknown tolerance policy {policy!r}")
        if key in self._registry:
            raise ReconciliationInputError(f"identity {key}: registered twice")
        info = IdentityInfo(key, stage, kind, title, basis, policy)
        self._registry[key] = info
        return info

    def _info(self, key: str) -> IdentityInfo:
        try:
            return self._registry[key]
        except KeyError:
            raise ReconciliationInputError(f"identity {key}: not registered") from None

    def _once(self, key: str, period: str | None) -> None:
        marker = (key, period)
        if marker in self._seen:
            raise ReconciliationInputError(f"identity {key}: period {period!r} evaluated twice (duplicate period)")
        self._seen.add(marker)

    # ── evaluation ────────────────────────────────────────────────────────────────────────────────
    def check(self, key: str, period: str | None, observed: Decimal, expected: Decimal, *,
              rounded_terms: int = 0) -> Outcome:
        info = self._info(key)
        policy = self.policies[info.tolerance_policy]
        self._once(key, period)
        residual = observed - expected
        abs_residual = abs(residual)
        scale = max(abs(observed), abs(expected))
        rel = abs_residual / scale if scale != 0 else Decimal(0)
        rep = representation_allowance(rounded_terms) if info.basis == BASIS_2DP else Decimal(0)
        allowance = max(policy.abs_tolerance, policy.rel_tolerance * scale) + rep
        status = "PASS" if abs_residual <= allowance else "FAIL"
        out = Outcome(key, info.stage, period, status,
                      "" if status == "PASS" else "OUTSIDE_APPROVED_ALLOWANCE", info.kind, info.basis,
                      policy.key, observed, expected, residual, abs_residual, rel, allowance, rep)
        self._outcomes.append(out)
        return out

    def _flag(self, key: str, period: str | None, status: str, reason: str) -> Outcome:
        info = self._info(key)
        self._once(key, period)
        out = Outcome(key, info.stage, period, status, reason, info.kind, info.basis, info.tolerance_policy)
        self._outcomes.append(out)
        return out

    def unavailable(self, key: str, period: str | None, reason: str) -> Outcome:
        """Evidence is absent.  Never replaced by zero."""
        return self._flag(key, period, "UNAVAILABLE", reason)

    def not_comparable(self, key: str, period: str | None, reason: str) -> Outcome:
        """Evidence exists but the axes, units or provenance cannot be proven to line up."""
        return self._flag(key, period, "NOT_COMPARABLE", reason)

    # ── results ───────────────────────────────────────────────────────────────────────────────────
    @property
    def outcomes(self) -> list[Outcome]:
        return list(self._outcomes)

    def finalise(self) -> dict[str, Any]:
        order = {stage: i for i, stage in enumerate(CATEGORIES)}
        key_order = {k: i for i, k in enumerate(self._registry)}
        ranked = sorted(self._outcomes, key=lambda o: (order[o.stage], key_order[o.identity], o.period or ""))
        first = next((o for o in ranked if o.status == "FAIL"), None)
        classified: list[Outcome] = []
        for o in ranked:
            label = ""
            if o.status == "FAIL":
                if first is not None and order[o.stage] > order[first.stage]:
                    label = CLASS_DOWNSTREAM
                else:
                    label = CLASS_INPUT if o.kind == KIND_INPUT else CLASS_CALCULATION
            classified.append(Outcome(**{**o.__dict__, "classification": label}))
        by_identity = []
        for key, info in self._registry.items():
            rows = [o for o in classified if o.identity == key]
            counts = {s: sum(r.status == s for r in rows) for s in STATES}
            residuals = [r.abs_residual for r in rows if r.abs_residual is not None]
            rels = [r.rel_residual for r in rows if r.rel_residual is not None]
            reasons = sorted({r.reason for r in rows if r.reason and r.status != "FAIL"})
            by_identity.append({
                "identity": key, "stage": info.stage, "kind": info.kind, "title": info.title,
                "basis": info.basis, "tolerance_policy": info.tolerance_policy,
                "evaluations": len(rows), "counts": counts,
                "max_abs_residual": _str(max(residuals)) if residuals else None,
                "max_rel_residual": _str(max(rels)) if rels else None,
                "reasons": reasons,
                "verdict": _verdict(counts),
            })
        counts = {s: sum(o.status == s for o in classified) for s in STATES}
        return {
            "schema": SCHEMA,
            "identity": self.identity,
            "tolerance_policies": {k: {"abs_tolerance": _str(p.abs_tolerance), "rel_tolerance": _str(p.rel_tolerance),
                                       "origin": p.origin, "justification": p.justification,
                                       "representation_quantum_for_persisted_2dp": _str(QUANTUM_2DP)}
                                   for k, p in sorted(self.policies.items())},
            "counts": counts,
            "first_divergence": None if first is None else {
                "identity": first.identity, "stage": first.stage, "period": first.period,
                "classification": next(o.classification for o in classified
                                       if o.identity == first.identity and o.period == first.period),
                "residual": _str(first.residual),
                "note": "Earliest FAIL in dependency order; later FAILs are not independent findings.",
            },
            "by_identity": by_identity,
            "outcomes": [_row(o) for o in classified],
        }


def _verdict(counts: dict[str, int]) -> str:
    if counts["FAIL"]:
        return "FAIL"
    if counts["PASS"] and not (counts["UNAVAILABLE"] or counts["NOT_COMPARABLE"]):
        return "VERIFIED"
    if counts["PASS"]:
        return "PARTIAL"
    if counts["NOT_COMPARABLE"]:
        return "NOT_COMPARABLE"
    return "UNAVAILABLE"


def _row(o: Outcome) -> dict[str, Any]:
    return {
        "identity": o.identity, "stage": o.stage, "period": o.period, "status": o.status, "reason": o.reason,
        "kind": o.kind, "classification": o.classification, "basis": o.basis, "tolerance_policy": o.tolerance_policy,
        "observed": _str(o.observed), "expected": _str(o.expected), "residual_observed_minus_expected": _str(o.residual),
        "absolute_residual": _str(o.abs_residual), "relative_residual": _str(o.rel_residual),
        "allowance": _str(o.allowance), "representation_allowance": _str(o.representation_allowance),
    }


CSV_FIELDS = ["identity", "stage", "period", "status", "reason", "kind", "classification", "basis", "tolerance_policy",
              "observed", "expected", "residual_observed_minus_expected", "absolute_residual", "relative_residual",
              "allowance", "representation_allowance"]


def reports(result: dict[str, Any]) -> dict[str, bytes]:
    """Deterministic JSON / CSV / Markdown for one reconciliation result.  Never embeds raw source payloads."""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(result["outcomes"])
    ident = result["identity"]
    md = ["# Numerical reconciliation of one committed Run", ""]
    for key in ("project_key", "scenario_key", "run_key", "snapshot_id", "composite_hash", "configuration_sha256",
                "engine_version", "financing_authority", "source_sha256"):
        if key in ident:
            md.append(f"- {key}: `{ident[key]}`")
    md += ["", "## Status counts", ""]
    md += [f"- {s}: {result['counts'][s]}" for s in STATES]
    md += ["", "## First divergence in dependency order", ""]
    first = result["first_divergence"]
    md.append("None: no identity FAILED." if first is None else
              f"{first['stage']} / {first['identity']} / {first['period']} — {first['classification']}. {first['note']}")
    md += ["", "## Tolerance policies (approved values and origin)", "",
           "| Policy | Absolute | Relative | Origin |", "| --- | ---: | ---: | --- |"]
    for key, p in result["tolerance_policies"].items():
        md.append(f"| {key} | {p['abs_tolerance']} | {p['rel_tolerance']} | {p['origin']} |")
    md += ["", "## Identities", "",
           "| Identity | Stage | Kind | Basis | Verdict | Evaluations | Max abs residual | Max rel residual | Notes |",
           "| --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |"]
    for row in result["by_identity"]:
        md.append("| " + " | ".join(str(v if v is not None else "—") for v in (
            row["identity"], row["stage"], row["kind"], row["basis"], row["verdict"], row["evaluations"],
            row["max_abs_residual"], row["max_rel_residual"], ", ".join(row["reasons"]))) + " |")
    md += ["", "A PASS or VERIFIED states only that the declared identity holds within its declared allowance for the "
           "evaluated periods. UNAVAILABLE and NOT_COMPARABLE are never treated as agreement.", ""]
    return {"report.json": canonical_bytes(result), "report.csv": buffer.getvalue().encode(),
            "report.md": ("\n".join(md)).encode()}
