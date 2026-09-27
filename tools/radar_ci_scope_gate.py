"""Apply Radar milestone scope isolation to a pull request's actual diff.

Functional regression coverage belongs to the workflows and is unconditional;
this gate only rejects upstream edits bundled with R5/R6-owned implementation.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys


_OWNED = {
    "r5": ("finco_radar/signals/", "finco_radar/history/", "finco_radar/r5/"),
    "r6": ("finco_radar/terminal/", "finco_radar/r6/"),
}
_UPSTREAM = {
    "r5": (
        "finco_radar/quotes/", "finco_radar/r0/", "finco_radar/assets/",
        "finco_radar/r1/", "finco_radar/gap/", "finco_radar/r2/",
        "finco_radar/liquidity/", "finco_radar/r3/",
        "finco_radar/reference_state/", "finco_radar/r4/",
        "financial_engine/", "finco_core/", "finco_protocol/",
    ),
    "r6": (
        "finco_radar/quotes/", "finco_radar/r0/", "finco_radar/assets/",
        "finco_radar/r1/", "finco_radar/gap/", "finco_radar/r2/",
        "finco_radar/liquidity/", "finco_radar/r3/",
        "finco_radar/reference_state/", "finco_radar/r4/",
        "finco_radar/signals/", "finco_radar/history/", "finco_radar/r5/",
        "financial_engine/", "finco_core/", "finco_protocol/",
    ),
}
_SHA = re.compile(r"[0-9a-f]{40}\Z")


def changed_paths(base: str, head: str) -> tuple[str, ...]:
    """Read the exact base-to-PR-head tree diff; never use milestone SHAs."""
    if not _SHA.fullmatch(base) or not _SHA.fullmatch(head):
        raise ValueError("base and head must be full lowercase commit SHAs")
    result = subprocess.run(
        ["git", "diff", "--name-only", "-z", base, head, "--"],
        check=True, capture_output=True,
    )
    return tuple(path.decode("utf-8") for path in result.stdout.split(b"\0") if path)


def scope_violations(milestone: str, paths: tuple[str, ...]) -> tuple[str, ...]:
    """Only an owned implementation edit activates that milestone's guard."""
    owned = _OWNED[milestone]
    if not any(path.startswith(owned) for path in paths):
        return ()
    upstream = _UPSTREAM[milestone]
    return tuple(path for path in paths if path.startswith(upstream))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("milestone", choices=tuple(_OWNED))
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args()
    try:
        paths = changed_paths(args.base, args.head)
        violations = scope_violations(args.milestone, paths)
    except (ValueError, subprocess.CalledProcessError) as exc:
        print(f"Radar {args.milestone.upper()} scope check could not run: {exc}", file=sys.stderr)
        return 2
    if violations:
        print(
            f"Radar {args.milestone.upper()} owned implementation changed together "
            "with unrelated upstream production paths:", file=sys.stderr,
        )
        for path in violations:
            print(f"  {path}", file=sys.stderr)
        return 1
    print(f"Radar {args.milestone.upper()} scope isolation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
