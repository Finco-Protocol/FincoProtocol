"""Decide the Model CI mode: STANDARD or FULL (FULL also runs the nodes in tests/full_regression_nodes.txt).

FULL when: the event is the nightly ``schedule``; the workflow was dispatched or called with ``full_regression: true``
(the release gate always does); or a ``pull_request`` / ``merge_group`` diff touches a path in
scripts/ci/full_regression_paths.txt. A diff that cannot be read is FULL (fail closed). Everything else is STANDARD.
Prints ``full=true|false`` and ``reason=...`` (GitHub step-output format).

Usage: ci_mode.py --event EVENT --full-input {true,false,""} [--base SHA --head SHA]
"""
import argparse
import subprocess
import sys

PATHS_FILE = "scripts/ci/full_regression_paths.txt"


def relevant_prefixes(path=PATHS_FILE):
    out = []
    for line in open(path, encoding="utf-8"):
        item = line.split("#", 1)[0].strip()
        if item:
            out.append(item)
    return out


def touched(changed, prefixes):
    return sorted(p for p in changed if any(p == x or (x.endswith("/") and p.startswith(x)) for x in prefixes))


def changed_files(base, head):
    out = subprocess.run(["git", "diff", "--name-only", "%s...%s" % (base, head)], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "git diff failed")
    return [line for line in out.stdout.splitlines() if line.strip()]


def decide(event, full_input, base=None, head=None, diff=changed_files, prefixes=None):
    if event == "schedule":
        return True, "nightly schedule"
    if str(full_input).lower() == "true":
        return True, "full_regression input"
    if event in ("pull_request", "merge_group"):
        if not base or not head:
            return True, "diff unreadable (missing base/head) -> FULL (fail closed)"
        try:
            files = diff(base, head)
        except Exception as exc:  # noqa: BLE001 - any failure to read the diff is fail-closed FULL
            return True, "diff unreadable (%s) -> FULL (fail closed)" % type(exc).__name__
        hits = touched(files, prefixes if prefixes is not None else relevant_prefixes())
        if hits:
            return True, "relevant paths changed: %s%s" % (", ".join(hits[:5]), " ..." if len(hits) > 5 else "")
        return False, "no relevant path changed (%d files)" % len(files)
    return False, "standard mode for event %s" % event


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", required=True)
    ap.add_argument("--full-input", default="")
    ap.add_argument("--base", default="")
    ap.add_argument("--head", default="")
    a = ap.parse_args(argv)
    full, reason = decide(a.event, a.full_input, a.base or None, a.head or None)
    print("full=%s" % ("true" if full else "false"))
    print("reason=%s" % reason.replace("\n", " "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
