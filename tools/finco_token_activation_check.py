"""Read-only $FINCO activation readiness report. Never activates anything; prints no RPC URL or secret."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.protocol.activation_readiness import ActivationStatus, assess_activation  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", help="JSON file with a PROPOSED deployment (validated, never authoritative)")
    args = parser.parse_args(argv)
    candidate = json.loads(Path(args.candidate).read_text()) if args.candidate else None
    report = asyncio.run(assess_activation(candidate=candidate))
    print(json.dumps(report.public_view(), indent=2, sort_keys=True))
    return 0 if report.status in (ActivationStatus.READY_FOR_ACTIVATION, ActivationStatus.ACTIVE) else 1


if __name__ == "__main__":
    raise SystemExit(main())
