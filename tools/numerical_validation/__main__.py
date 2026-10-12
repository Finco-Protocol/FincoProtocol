"""Run P0-B3 with user-authorised PRIVATE evidence only.

Example:
  python -m tools.numerical_validation --authorized-source \
    --manifest /private/S05_manifest.json --reference /private/source.json \
    --finco /private/finco.json --output /private/p0b3_result

The three input files must never be committed or uploaded to CI artifacts.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .reconcile import ReconciliationInputError, compare, reports


def _private_output(path: Path) -> Path:
    output = path.resolve()
    repo = Path(__file__).resolve().parents[2]
    try:
        relative = output.relative_to(repo)
    except ValueError:
        return output  # outside repository is private by deployment policy
    if not relative.parts or relative.parts[0] not in {"reports", "artifacts"}:
        raise ReconciliationInputError(
            "PRIVATE_OUTPUT_ONLY: inside repository, reports must be written under "
            "gitignored reports/ or artifacts/; use a private directory elsewhere"
        )
    return output


def run_cli(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generic private numerical reconciliation; no FINCO engine Run")
    parser.add_argument("--authorized-source", action="store_true",
                        help="affirm supplied reference evidence is authorised for this local use")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--finco", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.authorized_source:
        print("RECONCILIATION_BLOCKED: --authorized-source acknowledgement required", file=sys.stderr)
        return 3
    try:
        output = _private_output(args.output)
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        result = compare(manifest, args.reference.read_bytes(), args.finco.read_bytes())
        generated = reports(result)
        output.mkdir(parents=True, exist_ok=True)
        for filename in sorted(generated):
            dest = output / filename
            dest.write_bytes(generated[filename])
        print(json.dumps({"status": "PROVENANCE_BLOCKED" if result["provenance_blockers"] else
                          "NUMERICAL_COMPARISON_PRODUCED",
                          "counts": result["counts"], "provenance_blockers": result["provenance_blockers"],
                          "output_directory": str(output)}, sort_keys=True))
        # A comparison containing missing/uncomparable/failed rows is not a numerical acceptance.
        return 0 if (result["counts"]["FAIL"] == result["counts"]["UNAVAILABLE"] ==
                     result["counts"]["NOT_COMPARABLE"] == 0) else 2
    except (OSError, json.JSONDecodeError, ReconciliationInputError) as exc:
        print("RECONCILIATION_BLOCKED: " + str(exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(run_cli())
