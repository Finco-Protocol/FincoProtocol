"""Reconcile one committed FINCO Run against independent Decimal identities.

    # from an evidence bundle file
    python -m tools.numerical_validation.verify --bundle bundle.json --output artifacts/f39-run

    # straight from a database holding the immutable Run (read-only)
    python -m tools.numerical_validation.verify --db data/finco_runs.db --owner USER --project PROJECT_ID \\
        [--history HISTORY_ID] --output artifacts/f39-run

Exit codes: 0 = no identity failed and none was left unverifiable; 2 = at least one FAIL, UNAVAILABLE or
NOT_COMPARABLE outcome (a validation verdict, NOT an engine-correctness finding); 3 = malformed input or unsafe output.
Reports are written to a private location (outside the repository, or under the git-ignored reports/ or artifacts/).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .__main__ import _private_output
from .evidence import SCHEMA
from .identities import reconcile_bundle
from .periodic import reports
from .reconcile import ReconciliationInputError, _unique_json_object


def run_cli(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Independent numerical reconciliation of one committed Run")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--bundle", type=Path)
    source.add_argument("--db", type=Path)
    parser.add_argument("--owner")
    parser.add_argument("--project")
    parser.add_argument("--history")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output = _private_output(args.output)
        if args.bundle:
            bundle = json.loads(args.bundle.read_text(encoding="utf-8"), object_pairs_hook=_unique_json_object)
            if not isinstance(bundle, dict) or bundle.get("schema") != SCHEMA:
                raise ReconciliationInputError("BUNDLE: unsupported or missing schema")
        else:
            if not (args.owner and args.project):
                raise ReconciliationInputError("--owner and --project are required with --db")
            if not args.db.is_file():
                raise ReconciliationInputError("DB: file not found")
            os.environ["FINCO_DB_PATH"] = str(args.db.resolve())
            from .source import bundle_for_run

            bundle = bundle_for_run(args.owner, args.project, args.history)
        result = reconcile_bundle(bundle)
        generated = reports(result)
        output.mkdir(parents=True, exist_ok=True)
        for name, data in sorted(generated.items()):
            (output / name).write_bytes(data)
        print(json.dumps({"counts": result["counts"], "first_divergence": result["first_divergence"],
                          "output_directory": str(output)}, sort_keys=True))
        counts = result["counts"]
        return 0 if counts["FAIL"] == counts["UNAVAILABLE"] == counts["NOT_COMPARABLE"] == 0 else 2
    except (OSError, json.JSONDecodeError, ReconciliationInputError, LookupError, ValueError) as exc:
        print("RECONCILIATION_BLOCKED: " + str(exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(run_cli())
