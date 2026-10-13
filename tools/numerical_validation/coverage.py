"""F3.9 four-vertical coverage matrix: which identity is VERIFIED, PARTIAL, NOT_APPLICABLE or UNAVAILABLE per configuration.

Pure: it consumes the results of ``identities.reconcile_bundle`` (one per labelled configuration) and renders a
deterministic matrix.  An identity that is not applicable to a configuration (no second facility, no Junior facility)
is reported NOT_APPLICABLE; one whose input is not persisted stays UNAVAILABLE.  Nothing is ever promoted to PASS.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any, Mapping

from .evidence import UNSUPPORTED

SCHEMA = "FINCO_NUMERICAL_COVERAGE_V1"
NOT_APPLICABLE = "NOT_APPLICABLE"
_NA_PREFIX = "NO_"
_NA_REASONS = ("REPORTED_SENIOR_TOTAL_SPANS_SENIOR_AND_JUNIOR", "REPORTED_SERVICE_SPANS_SENIOR_AND_JUNIOR")


def _cell(row: Mapping[str, Any]) -> dict[str, Any]:
    verdict = row["verdict"]
    reasons = list(row["reasons"])
    if verdict in ("UNAVAILABLE", "NOT_COMPARABLE") and reasons and all(
            r.startswith(_NA_PREFIX) or r in _NA_REASONS for r in reasons):
        verdict = NOT_APPLICABLE
    return {"verdict": verdict, "counts": row["counts"], "max_abs_residual": row["max_abs_residual"], "reasons": reasons}


def build_matrix(results: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """``results`` maps a configuration label (for example ``solar/legacy``) to a reconciliation result."""
    labels = sorted(results)
    identities: dict[str, dict[str, Any]] = {}
    for label in labels:
        for row in results[label]["by_identity"]:
            entry = identities.setdefault(row["identity"], {"stage": row["stage"], "title": row["title"], "cells": {}})
            entry["cells"][label] = _cell(row)
    totals = {label: results[label]["counts"] for label in labels}
    failing = sorted(label for label in labels if results[label]["counts"]["FAIL"])
    return {
        "schema": SCHEMA,
        "configurations": labels,
        "identities": {k: identities[k] for k in sorted(identities)},
        "totals": totals,
        "configurations_with_fail": failing,
        "unsupported_capabilities": [{"capability": k, "reason": v} for k, v in UNSUPPORTED],
    }


def to_json(matrix: Mapping[str, Any]) -> bytes:
    return (json.dumps(matrix, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def to_csv(matrix: Mapping[str, Any]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["identity", "stage", *matrix["configurations"]])
    for key, entry in matrix["identities"].items():
        writer.writerow([key, entry["stage"], *[entry["cells"].get(c, {}).get("verdict", "") for c in matrix["configurations"]]])
    return buffer.getvalue().encode("utf-8")


def to_markdown(matrix: Mapping[str, Any]) -> bytes:
    labels = matrix["configurations"]
    lines = ["# F3.9 four-vertical coverage matrix", "",
             "| Identity | Stage | " + " | ".join(labels) + " |", "|---|---|" + "---|" * len(labels)]
    for key, entry in matrix["identities"].items():
        lines.append(f"| {key} | {entry['stage']} | " + " | ".join(
            entry["cells"].get(c, {}).get("verdict", "") for c in labels) + " |")
    lines += ["", "## Outcome totals", "", "| Configuration | PASS | FAIL | UNAVAILABLE | NOT_COMPARABLE |", "|---|---|---|---|---|"]
    for label in labels:
        t = matrix["totals"][label]
        lines.append(f"| {label} | {t['PASS']} | {t['FAIL']} | {t['UNAVAILABLE']} | {t['NOT_COMPARABLE']} |")
    lines += ["", "## Unsupported capabilities", ""]
    lines += [f"* `{u['capability']}` — {u['reason']}" for u in matrix["unsupported_capabilities"]]
    return ("\n".join(lines) + "\n").encode("utf-8")


def render(results: Mapping[str, Mapping[str, Any]]) -> dict[str, bytes]:
    matrix = build_matrix(results)
    return {"coverage.json": to_json(matrix), "coverage.csv": to_csv(matrix), "coverage.md": to_markdown(matrix)}
