"""Offline CLI: validate | compare | explain | export-candidates.

Deterministic output (sorted JSON); exit code 2 when a validate/compare input
contains rejected rows. Never produces a computed project tax rate.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from decimal import Decimal
from typing import Sequence

from tax_reference_registry.loader import (
    LoadResult,
    RecordFormatError,
    load_records,
)
from tax_reference_registry.registry import TaxReferenceRegistry, UnknownRuleError

EXIT_OK = 0
EXIT_INVALID = 2


def _load_many(paths: Sequence[str], markers: Sequence[str]) -> list[LoadResult]:
    results = []
    for path in paths:
        results.append(
            load_records(path, source_path=path, private_markers=markers)
        )
    return results


def _merged(results: Sequence[LoadResult]) -> TaxReferenceRegistry:
    records = []
    for result in results:
        records.extend(result.records)
    return TaxReferenceRegistry.from_records(records, as_of=_dt.date(2026, 11, 7))


def _emit(report: dict, out_path: str | None) -> None:
    text = json.dumps(report, indent=1, sort_keys=True, ensure_ascii=False)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    else:
        sys.stdout.write(text + "\n")


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        results = _load_many(args.files, args.private_marker)
    except RecordFormatError as exc:
        _emit({"valid": 0, "invalid": 0, "format_error": str(exc)}, args.report)
        return EXIT_INVALID
    rows = []
    for result in results:
        report = result.report()
        rows.extend(report["rows"])
    rows.sort(key=lambda r: (r["jurisdiction_code"], r["rule_id"], r["status"]))
    records = [r for result in results for r in result.records]
    errors = [e for result in results for e in result.errors]
    registry = TaxReferenceRegistry.from_records(
        records, as_of=_dt.date(2026, 11, 7)
    )
    report = {
        "valid": len(records),
        "invalid": len(errors),
        "unverified": sum(
            1
            for r in records
            if r.verification.value != "PRIMARY_CONFIRMED"
        ),
        "conflict": sum(
            1 for r in records if r.verification.value == "CONFLICT"
        ),
        "countries": sorted(registry.countries()),
        "rules": len(records),
        "warnings": sum(len(result.warnings) for result in results),
        "activation": "NON_ACTIVATABLE_REFERENCE_ONLY (all profiles CANDIDATE_NOT_ACTIVE)",
        "rows": rows,
    }
    _emit(report, args.report)
    return EXIT_OK if not errors else EXIT_INVALID


def cmd_compare(args: argparse.Namespace) -> int:
    try:
        old_results = _load_many([args.old_file], args.private_marker)
        new_results = _load_many([args.new_file], args.private_marker)
    except RecordFormatError as exc:
        _emit({"format_error": str(exc)}, args.report)
        return EXIT_INVALID
    old_registry = _merged(old_results)
    new_registry = _merged(new_results)
    day = (
        _dt.datetime.strptime(args.as_of, "%Y-%m-%d").date()
        if args.as_of
        else _dt.date(2026, 11, 7)
    )
    report = new_registry.compare(old_registry, reference_day=day)
    report["activation"] = "NON_ACTIVATABLE_REFERENCE_ONLY"
    _emit(report, args.report)
    return EXIT_OK


def cmd_explain(args: argparse.Namespace) -> int:
    try:
        registry = _merged(_load_many(args.files, args.private_marker))
        result = registry.explain(args.country, args.rule_id)
    except (RecordFormatError, UnknownRuleError) as exc:
        _emit({"error": str(exc)}, args.report)
        return EXIT_INVALID
    payload = result.as_dict()
    payload["activation"] = "NON_ACTIVATABLE_REFERENCE_ONLY"
    payload["note"] = (
        "This is a reference explanation with source citations and evidence "
        "status. It is not a computed project tax rate."
    )
    _emit(payload, args.report)
    return EXIT_OK


def cmd_export_candidates(args: argparse.Namespace) -> int:
    try:
        registry = _merged(_load_many(args.files, args.private_marker))
    except RecordFormatError as exc:
        _emit({"format_error": str(exc)}, args.report)
        return EXIT_INVALID
    report = registry.export_candidates()
    if args.format == "text":
        lines = [report["tag"], "", f"countries: {len(report['countries'])}", f"rules: {report['rules']}", ""]
        for row in report["candidates"]:
            lines.append(
                f"{row['rule_id']}  {row['jurisdiction_code']}  "
                f"{row['tax_category']}  value={row['value']} "
                f"{row['value_unit'] or ''} [{row['law_status']} / "
                f"{row['verification']}]"
            )
        text = "\n".join(lines) + "\n"
        if args.out:
            with open(args.out, "w", encoding="utf-8") as handle:
                handle.write(text)
        else:
            sys.stdout.write(text)
        return EXIT_OK
    _emit(report, args.out)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tax_reference_registry",
        description=(
            "Offline reference registry for statutory tax-rule evidence. "
            "Reference-only: never computes project tax rates and never "
            "activates a country profile."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    marker_arg = {
        "action": "append",
        "default": [],
        "help": "private-metadata marker; rows containing it are rejected",
    }

    p_validate = sub.add_parser("validate", help="validate CSV dataset(s)")
    p_validate.add_argument("files", nargs="+")
    p_validate.add_argument("--report")
    p_validate.add_argument("--private-marker", **marker_arg)
    p_validate.set_defaults(func=cmd_validate)

    p_compare = sub.add_parser("compare", help="diff two dataset versions")
    p_compare.add_argument("old_file")
    p_compare.add_argument("new_file")
    p_compare.add_argument("--report")
    p_compare.add_argument("--as-of", dest="as_of")
    p_compare.add_argument("--private-marker", **marker_arg)
    p_compare.set_defaults(func=cmd_compare)

    p_explain = sub.add_parser("explain", help="explain one rule with citations")
    p_explain.add_argument("country")
    p_explain.add_argument("rule_id")
    p_explain.add_argument("files", nargs="+")
    p_explain.add_argument("--report")
    p_explain.add_argument("--private-marker", **marker_arg)
    p_explain.set_defaults(func=cmd_explain)

    p_export = sub.add_parser("export-candidates", help="NON_ACTIVATABLE summary")
    p_export.add_argument("files", nargs="+")
    p_export.add_argument("--format", choices=["json", "text"], default="json")
    p_export.add_argument("--out")
    p_export.add_argument("--private-marker", **marker_arg)
    p_export.set_defaults(func=cmd_export_candidates)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
