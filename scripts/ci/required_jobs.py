"""Model CI `required` aggregate: every required job concluded success.

The only exemption: ``full-regression`` may be ``skipped`` when (and only when) the ``mode`` job decided STANDARD. In FULL
mode it must be ``success`` like every other job; skipped, cancelled, failed or missing is a failure in every mode.
Reads ``toJSON(needs)`` from $RESULTS. Exit 1 and print REQUIRED FAILED on any violation.
"""
import json
import os
import sys

EXPECTED = {"mode", "static", "boot-smoke", "finance", "tests", "acceptance", "full-regression"}


def evaluate(needs):
    problems = []
    if set(needs) != EXPECTED:
        problems.append("job set mismatch: %s" % sorted(EXPECTED ^ set(needs)))
        return problems
    mode = needs["mode"]
    if mode.get("result") != "success":
        return ["mode: %s" % mode.get("result")]
    full = (mode.get("outputs") or {}).get("full")
    if full not in ("true", "false"):
        return ["mode output 'full' is %r (expected true/false)" % (full,)]
    for name, value in sorted(needs.items()):
        result = value.get("result")
        if name == "full-regression" and full == "false":
            if result != "skipped":
                problems.append("full-regression ran (%s) although mode is STANDARD" % result)
            continue
        if result != "success":
            problems.append("%s: %s" % (name, result))
    return problems


def main():
    needs = json.loads(os.environ["RESULTS"])
    problems = evaluate(needs)
    if problems:
        print("REQUIRED FAILED:", "; ".join(problems))
        return 1
    full = needs["mode"]["outputs"]["full"] == "true"
    print("all required jobs: success (mode %s%s)" % ("FULL" if full else "STANDARD",
          ": full-regression executed" if full else ": full-regression deferred to FULL runs"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
