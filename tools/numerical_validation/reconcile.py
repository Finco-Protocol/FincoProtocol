"""P0-B3 generic numerical reconciliation (validation only, NOT a financial engine).

Inputs are independently authorised, already-normalised output snapshots. Values,
identities, units, tolerances and provenance are never inferred or fitted.
Importing this module does not import or invoke the FINCO financial engine.
The CLI requires private/ignored report destinations.
"""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from pathlib import Path
from typing import Any

CATEGORIES = (
    "assumptions", "generation", "revenue", "opex_ebitda", "capex_funding",
    "debt", "statements", "tax", "cfads_waterfall", "returns",
)
STATES = ("PASS", "FAIL", "UNAVAILABLE", "NOT_COMPARABLE")
SCHEMA_VERSION = 1


class ReconciliationInputError(ValueError):
    """Malformed, contradictory or untrusted comparison request."""


def _obj(value: Any, keys: set[str], *, required: set[str] | None = None, where: str):
    if type(value) is not dict or set(value) - keys or (required or keys) - set(value):
        raise ReconciliationInputError(f"{where}: missing/unknown keys")
    return value


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ReconciliationInputError(f"{label}: non-empty bounded text required")
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ReconciliationInputError(f"{label}: lowercase SHA-256 required")
    return value


def _decimal(value: Any, label: str, *, nonnegative: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ReconciliationInputError(f"{label}: invalid decimal")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ReconciliationInputError(f"{label}: invalid decimal") from exc
    if not number.is_finite() or (nonnegative and number < 0):
        raise ReconciliationInputError(f"{label}: nonfinite or negative value")
    return number


def _timestamp(value: Any, label: str) -> str:
    from datetime import datetime
    text = _nonempty(value, label)
    try:
        ts = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReconciliationInputError(f"{label}: ISO timestamp required") from exc
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ReconciliationInputError(f"{label}: timezone required")
    return text


def _date(value: Any, label: str) -> str:
    from datetime import date
    text = _nonempty(value, label)
    try:
        if date.fromisoformat(text).isoformat() != text:
            raise ValueError()
    except ValueError as exc:
        raise ReconciliationInputError(f"{label}: ISO date required") from exc
    return text


@dataclass(frozen=True)
class EvidenceIdentity:
    project_key: str
    scenario_key: str
    configuration_sha256: str
    run_key: str
    calculated_at: str
    engine_version: str
    output_sha256: str
    currency: str
    calendar: str
    conventions_sha256: str

    @classmethod
    def from_data(cls, value: dict, prefix: str):
        _obj(value, set(cls.__dataclass_fields__), where=prefix)
        return cls(
            project_key=_nonempty(value["project_key"], prefix + ".project_key"),
            scenario_key=_nonempty(value["scenario_key"], prefix + ".scenario_key"),
            configuration_sha256=_sha(value["configuration_sha256"], prefix + ".configuration_sha256"),
            run_key=_nonempty(value["run_key"], prefix + ".run_key"),
            calculated_at=_timestamp(value["calculated_at"], prefix + ".calculated_at"),
            engine_version=_nonempty(value["engine_version"], prefix + ".engine_version"),
            output_sha256=_sha(value["output_sha256"], prefix + ".output_sha256"),
            currency=_nonempty(value["currency"], prefix + ".currency").upper(),
            calendar=_nonempty(value["calendar"], prefix + ".calendar"),
            conventions_sha256=_sha(value["conventions_sha256"], prefix + ".conventions_sha256"),
        )


@dataclass(frozen=True)
class Period:
    key: str
    start: str
    end: str

    @classmethod
    def from_data(cls, item: dict, label: str):
        _obj(item, {"key", "start", "end"}, where=label)
        result = cls(_nonempty(item["key"], label + ".key"),
                     _date(item["start"], label + ".start"),
                     _date(item["end"], label + ".end"))
        if result.end <= result.start:
            raise ReconciliationInputError(label + ": end must be after start")
        return result


@dataclass(frozen=True)
class PeriodPair:
    reference: Period
    finco: Period

    @classmethod
    def from_data(cls, item: dict, label: str):
        _obj(item, {"reference", "finco"}, where=label)
        return cls(Period.from_data(item["reference"], label + ".reference"),
                   Period.from_data(item["finco"], label + ".finco"))


@dataclass(frozen=True)
class MetricMap:
    key: str
    stage: str
    reference_metric: str
    finco_metric: str
    unit: str
    abs_tolerance: Decimal
    rel_tolerance: Decimal

    @classmethod
    def from_data(cls, item: dict, label: str):
        _obj(item, {"key", "stage", "reference_metric", "finco_metric", "unit",
                    "abs_tolerance", "rel_tolerance"}, where=label)
        stage = _nonempty(item["stage"], label + ".stage")
        if stage not in CATEGORIES:
            raise ReconciliationInputError(label + ": unsupported dependency stage")
        return cls(
            _nonempty(item["key"], label + ".key"), stage,
            _nonempty(item["reference_metric"], label + ".reference_metric"),
            _nonempty(item["finco_metric"], label + ".finco_metric"),
            _nonempty(item["unit"], label + ".unit"),
            _decimal(item["abs_tolerance"], label + ".abs_tolerance", nonnegative=True),
            _decimal(item["rel_tolerance"], label + ".rel_tolerance", nonnegative=True),
        )


@dataclass(frozen=True)
class Manifest:
    reference: EvidenceIdentity
    finco: EvidenceIdentity
    periods: tuple[PeriodPair, ...]
    metrics: tuple[MetricMap, ...]
    reference_export_version: str
    reference_parsed_version: str
    version: int = SCHEMA_VERSION

    @classmethod
    def from_data(cls, item: dict):
        _obj(item, {"version", "reference", "finco", "periods", "metrics",
                    "reference_export_version", "reference_parsed_version"}, where="manifest")
        if type(item["version"]) is not int or item["version"] != SCHEMA_VERSION:
            raise ReconciliationInputError("manifest: unsupported version")
        if not isinstance(item["periods"], list) or not item["periods"]:
            raise ReconciliationInputError("manifest: explicit period mapping required")
        if not isinstance(item["metrics"], list) or not item["metrics"]:
            raise ReconciliationInputError("manifest: explicit metric mapping required")
        periods = tuple(PeriodPair.from_data(v, f"periods[{i}]") for i, v in enumerate(item["periods"]))
        metrics = tuple(MetricMap.from_data(v, f"metrics[{i}]") for i, v in enumerate(item["metrics"]))
        for label, keys in (
            ("period.reference", [p.reference.key for p in periods]),
            ("period.finco", [p.finco.key for p in periods]),
            ("metric.key", [m.key for m in metrics]),
            ("metric.reference", [m.reference_metric for m in metrics]),
            ("metric.finco", [m.finco_metric for m in metrics]),
        ):
            if len(set(keys)) != len(keys):
                raise ReconciliationInputError(label + ": duplicate mapping identity")
        reference = EvidenceIdentity.from_data(item["reference"], "reference")
        finco = EvidenceIdentity.from_data(item["finco"], "finco")
        if (reference.project_key, reference.scenario_key, reference.configuration_sha256) != (
                finco.project_key, finco.scenario_key, finco.configuration_sha256):
            raise ReconciliationInputError("PROVENANCE: project/scenario/configuration mismatch (no comparison)")
        return cls(
            reference, finco, periods, metrics,
            _nonempty(item["reference_export_version"], "reference_export_version"),
            _nonempty(item["reference_parsed_version"], "reference_parsed_version"),
        )


@dataclass(frozen=True)
class Observation:
    metric: str
    period: str
    value: Decimal | None
    unit: str
    currency: str


def observations(doc: dict, label: str) -> dict[tuple[str, str], Observation]:
    _obj(doc, {"rows"}, where=label)
    if not isinstance(doc["rows"], list):
        raise ReconciliationInputError(label + ": rows must be list")
    output: dict[tuple[str, str], Observation] = {}
    for i, value in enumerate(doc["rows"]):
        prefix = f"{label}.rows[{i}]"
        _obj(value, {"metric", "period", "value", "unit", "currency"}, where=prefix)
        row = Observation(
            metric=_nonempty(value["metric"], prefix + ".metric"),
            period=_nonempty(value["period"], prefix + ".period"),
            value=None if value["value"] is None else _decimal(value["value"], prefix + ".value"),
            unit=_nonempty(value["unit"], prefix + ".unit"),
            currency=_nonempty(value["currency"], prefix + ".currency").upper(),
        )
        key = (row.metric, row.period)
        if key in output:
            raise ReconciliationInputError(prefix + ": duplicate output identity")
        output[key] = row
    return output


def _str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _unique_json_object(pairs):
    """Forbid duplicate identities inside individual JSON objects before parsing."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReconciliationInputError("OUTPUT: duplicate JSON object key")
        result[key] = value
    return result


def canonical_bytes(doc: Any) -> bytes:
    return (json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                       allow_nan=False) + "\n").encode("utf-8")


def compare(manifest_data: dict, reference_bytes: bytes, finco_bytes: bytes) -> dict:
    """Fully checked, deterministic read-only comparison. No automatic defect labels."""
    manifest = Manifest.from_data(manifest_data)
    if sha256_bytes(reference_bytes) != manifest.reference.output_sha256:
        raise ReconciliationInputError("PROVENANCE: reference evidence SHA mismatch")
    if sha256_bytes(finco_bytes) != manifest.finco.output_sha256:
        raise ReconciliationInputError("PROVENANCE: FINCO evidence SHA mismatch")
    try:
        left = observations(json.loads(reference_bytes, object_pairs_hook=_unique_json_object), "reference")
        right = observations(json.loads(finco_bytes, object_pairs_hook=_unique_json_object), "finco")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReconciliationInputError("OUTPUT: malformed evidence JSON") from exc

    # An internal source version conflict disqualifies every numeric result.
    conflicts = []
    if manifest.reference_export_version != manifest.reference_parsed_version:
        conflicts.append("SOURCE_ENGINE_VERSION_CONFLICT")
    if manifest.reference.engine_version != manifest.reference_export_version:
        conflicts.append("REFERENCE_ENGINE_NOT_ATTESTED")
    if manifest.reference.currency != manifest.finco.currency:
        conflicts.append("CURRENCY_NOT_NORMALIZED")
    if manifest.reference.calendar != manifest.finco.calendar:
        conflicts.append("CALENDAR_NOT_NORMALIZED")
    if manifest.reference.conventions_sha256 != manifest.finco.conventions_sha256:
        conflicts.append("CONVENTIONS_NOT_ALIGNED")
    blockers = sorted(set(conflicts))

    results = []
    for metric in manifest.metrics:
        for period in manifest.periods:
            a = left.get((metric.reference_metric, period.reference.key))
            b = right.get((metric.finco_metric, period.finco.key))
            status, reason, delta, abs_delta, rel_delta, allowance = "PASS", "", None, None, None, None
            if blockers:
                status, reason = "NOT_COMPARABLE", ",".join(blockers)
            elif (period.reference.start, period.reference.end) != (period.finco.start, period.finco.end):
                status, reason = "NOT_COMPARABLE", "PERIOD_AXIS_MISMATCH"
            elif a is None or b is None or a.value is None or b.value is None:
                status, reason = "UNAVAILABLE", "MISSING_SOURCE_OR_FINCO_VALUE"
            elif (a.unit, b.unit) != (metric.unit, metric.unit):
                status, reason = "NOT_COMPARABLE", "UNIT_NOT_NORMALIZED"
            elif (a.currency, b.currency) != (manifest.reference.currency, manifest.finco.currency):
                status, reason = "NOT_COMPARABLE", "OBSERVATION_CURRENCY_MISMATCH"
            else:
                delta = b.value - a.value
                abs_delta = abs(delta)
                scale = max(abs(a.value), abs(b.value))
                rel_delta = abs_delta / scale if scale != 0 else Decimal(0)
                allowance = max(metric.abs_tolerance, metric.rel_tolerance * scale)
                if abs_delta > allowance:
                    status, reason = "FAIL", "OUTSIDE_APPROVED_TOLERANCE"
            results.append({
                "key": metric.key, "stage": metric.stage,
                "reference_metric": metric.reference_metric, "finco_metric": metric.finco_metric,
                "reference_period": period.reference.key, "finco_period": period.finco.key,
                "unit": metric.unit, "status": status, "reason": reason,
                "reference_value": _str(a.value) if a else None,
                "finco_value": _str(b.value) if b else None,
                "delta_finco_minus_reference": _str(delta),
                "absolute_difference": _str(abs_delta), "relative_difference": _str(rel_delta),
                "tolerance_allowance": _str(allowance),
            })
    results.sort(key=lambda x: (CATEGORIES.index(x["stage"]), x["key"], x["reference_period"], x["finco_period"]))
    first = next((r for r in results if r["status"] == "FAIL"), None)
    counts = {state: sum(r["status"] == state for r in results) for state in STATES}
    return {
        "schema": SCHEMA_VERSION,
        "identity": {
            "project_key": manifest.reference.project_key,
            "scenario_key": manifest.reference.scenario_key,
            "configuration_sha256": manifest.reference.configuration_sha256,
            "reference_run": manifest.reference.run_key, "finco_run": manifest.finco.run_key,
            "reference_engine": manifest.reference.engine_version,
            "finco_engine": manifest.finco.engine_version,
            "reference_calculated_at": manifest.reference.calculated_at,
            "finco_calculated_at": manifest.finco.calculated_at,
            "reference_sha256": manifest.reference.output_sha256,
            "finco_sha256": manifest.finco.output_sha256,
        },
        "provenance_blockers": blockers,
        "counts": counts,
        "first_material_divergence": None if first is None else {
            "stage": first["stage"], "metric": first["key"], "period": first["reference_period"],
            "classification": "UPSTREAM_DIFFERENCE_REQUIRES_INVESTIGATION",
        },
        "results": results,
    }


def reports(result: dict) -> dict[str, bytes]:
    """Deterministic private JSON/CSV/Markdown; never embeds source documents."""
    encoded = canonical_bytes(result)
    output = io.StringIO(newline="")
    fields = ["key", "stage", "reference_metric", "finco_metric", "reference_period",
              "finco_period", "unit", "status", "reason", "reference_value", "finco_value",
              "delta_finco_minus_reference", "absolute_difference", "relative_difference",
              "tolerance_allowance"]
    csv_writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    csv_writer.writeheader()
    csv_writer.writerows(result["results"])
    markdown = ["# Private numerical reconciliation", "",
                f"Project: {result['identity']['project_key']}",
                f"Scenario: {result['identity']['scenario_key']}", "",
                "## Status counts", ""]
    markdown.extend(f"- {status}: {result['counts'][status]}" for status in STATES)
    markdown += ["", "## First material divergence", ""]
    first = result["first_material_divergence"]
    markdown.append("Not established." if first is None else
                    f"{first['stage']} / {first['metric']} / {first['period']} — investigate upstream first.")
    markdown += ["", "## Provenance blockers", ""]
    markdown.extend("- " + item for item in result["provenance_blockers"])
    if not result["provenance_blockers"]:
        markdown.append("- None detected by the typed manifest; independent authority still required.")
    markdown += ["", "## Metric-level reconciliation", "",
                 "| Stage | Metric | Period | Status | FINCO - reference | Reason |",
                 "| --- | --- | --- | --- | ---: | --- |"]
    for row in result["results"]:
        markdown.append("| " + " | ".join(str(v if v is not None else "—") for v in (
            row["stage"], row["key"], row["reference_period"], row["status"],
            row["delta_finco_minus_reference"], row["reason"])) + " |")
    return {"report.json": encoded, "report.csv": output.getvalue().encode(),
            "report.md": ("\n".join(markdown) + "\n").encode()}
