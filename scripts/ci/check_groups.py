"""Model CI aggregate check over the test groups' accounting files (written by tests/conftest.py, FINCO_CI_COUNTS).

Every group must have collected the same full node set; the groups' selections must be disjoint and, together with the
listed known defects and the nodes DEFERRED_TO_FULL (tests/full_regression_nodes.txt), equal that full collection; and
every selected node must appear in the group's JUnit report. Every listed known defect / deferred node must really be in
the collection (membership, not only arithmetic).

``--full``: the FULL regression job's accounting (counts-full.json / junit-full.xml) must exist, must have selected
exactly the deferred nodes, and each must have passed in its JUnit (not failed, errored or skipped); the deferred nodes
are then counted as executed exactly once. Without ``--full`` (STANDARD mode) a FULL accounting file must not exist and
the deferred nodes are reported as DEFERRED_TO_FULL (never as passed or skipped).
"""
import argparse
import glob
import json
import os
import sys
import xml.etree.ElementTree as ET


def known(path):
    out = set()
    for line in open(path, encoding="utf-8"):
        line = line.split("#", 1)[0].strip()
        if line:
            out.add(line)
    return out


def junit_cases(path):
    cases = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        bad = [c.tag for c in case if c.tag in ("failure", "error", "skipped")]
        cases[(case.get("classname", ""), case.get("name", ""))] = bad
    return cases


def junit_ids(path):
    return set(junit_cases(path))


def as_junit(nodeid):
    path, _, rest = nodeid.partition("::")
    parts = rest.split("::")
    module = path[:-3].replace("/", ".")
    return (".".join([module, *parts[:-1]]), parts[-1])


def _one(root, pattern):
    return glob.glob(os.path.join(root, "**", pattern), recursive=True)


def check(root, groups, known_defects, deferred=frozenset(), full=False):
    problems = []
    counts = {}
    if known_defects & deferred:
        problems.append("a node is both a known defect and deferred: %s" % sorted(known_defects & deferred)[:3])
    for i in range(1, groups + 1):
        files = _one(root, "counts-%d.json" % i)
        if len(files) != 1:
            problems.append("group %d: expected one accounting file, found %d" % (i, len(files)))
            continue
        counts[i] = json.load(open(files[0], encoding="utf-8"))
        junit = _one(root, "junit-%d.xml" % i)
        if len(junit) != 1:
            problems.append("group %d: missing JUnit" % i)
            continue
        reported = junit_ids(junit[0])
        missing = [n for n in counts[i]["selected"] if as_junit(n) not in reported]
        if missing:
            problems.append("group %d: %d selected nodes absent from JUnit, e.g. %s" % (i, len(missing), missing[:3]))
        if not counts[i]["selected"]:
            problems.append("group %d selected no test" % i)
    full_counts = None
    full_files = _one(root, "counts-full.json")
    if full:
        if len(full_files) != 1 or len(_one(root, "junit-full.xml")) != 1:
            problems.append("FULL mode: the full-regression job's accounting/JUnit is missing (found %d counts files)" % len(full_files))
        else:
            full_counts = json.load(open(full_files[0], encoding="utf-8"))
            cases = junit_cases(_one(root, "junit-full.xml")[0])
            if set(full_counts["selected"]) != set(deferred) or len(full_counts["selected"]) != len(deferred):
                problems.append("FULL job selected %s, expected exactly the deferred nodes %s"
                                % (sorted(full_counts["selected"])[:3], sorted(deferred)[:3]))
            for n in deferred:
                outcome = cases.get(as_junit(n))
                if outcome is None:
                    problems.append("FULL job JUnit has no result for deferred node %s" % n)
                elif outcome:
                    problems.append("FULL job deferred node %s did not pass (%s)" % (n, ",".join(outcome)))
    elif full_files:
        problems.append("STANDARD mode but a FULL accounting file exists (mode wiring inconsistent)")
    if problems:
        return problems
    # The FULL job invokes pytest with the exact deferred node id(s), so its own collection is exactly those node(s):
    # it is reconciled by selection (== deferred, checked above) and the deferred nodes' membership in the groups' full
    # collection (listed_present, below), not by comparing its collection digest with the groups'.
    if full_counts is not None and full_counts["collected"] != len(deferred):
        return ["FULL job collected %d node(s), expected exactly the %d deferred" % (full_counts["collected"], len(deferred))]
    digests = {c["collected_digest"] for c in counts.values()}
    totals = {c["collected"] for c in counts.values()}
    if len(digests) != 1 or len(totals) != 1:
        return ["groups collected different node sets: %s" % sorted(totals)]
    total = totals.pop()
    listed = known_defects | set(deferred)
    for i, c in counts.items():
        present = set(c.get("listed_present", []))
        absent = sorted(listed - present)
        if absent:
            problems.append("group %d: listed known-defect/deferred node(s) not in the collection: %s" % (i, absent[:3]))
            break
    seen = {}
    for i, c in counts.items():
        for n in c["selected"]:
            if n in seen:
                problems.append("node %s ran in groups %d and %d" % (n, seen[n], i))
            seen[n] = i
    if set(seen) & known_defects:
        problems.append("a known defect ran in a required group: %s" % sorted(set(seen) & known_defects)[:3])
    if set(seen) & set(deferred):
        problems.append("a deferred node ran in a standard group: %s" % sorted(set(seen) & set(deferred))[:3])
    executed = len(seen) + (len(full_counts["selected"]) if full_counts is not None else 0)
    deferred_n = 0 if full_counts is not None else len(deferred)
    if executed + deferred_n + len(known_defects) != total:
        problems.append("executed %d + deferred %d + %d known defects != %d collected"
                        % (executed, deferred_n, len(known_defects), total))
    if not problems:
        mode = "FULL" if full_counts is not None else "STANDARD"
        print("groups ok [%s]: %d collected = %d executed + %d deferred to FULL + %d known defects, %d groups%s"
              % (mode, total, executed, deferred_n, len(known_defects), groups,
                 " + full-regression job" if full_counts is not None else ""))
        for n in sorted(deferred):
            print(("  FULL executed and passed: " if full_counts is not None else "  DEFERRED_TO_FULL (not run in this mode): ") + n)
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--groups", type=int, required=True)
    ap.add_argument("--known-defects", required=True)
    ap.add_argument("--deferred", default=None, help="tests/full_regression_nodes.txt")
    ap.add_argument("--full", action="store_true", help="FULL mode: the full-regression job must have run the deferred nodes")
    a = ap.parse_args(argv)
    deferred = known(a.deferred) if a.deferred else set()
    problems = check(a.root, a.groups, known(a.known_defects), frozenset(deferred), a.full)
    for p in problems:
        print("GROUP CHECK FAILED:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
