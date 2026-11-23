"""Model CI aggregate check over the test groups' accounting files (written by tests/conftest.py, FINCO_CI_COUNTS).

Every group must have collected the same full node set; the groups' selections must be disjoint and, together with the
listed known defects, equal that full collection; and every selected node must appear in the group's JUnit report.
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


def junit_ids(path):
    ids = set()
    for case in ET.parse(path).getroot().iter("testcase"):
        ids.add((case.get("classname", ""), case.get("name", "")))
    return ids


def as_junit(nodeid):
    path, _, rest = nodeid.partition("::")
    parts = rest.split("::")
    module = path[:-3].replace("/", ".")
    return (".".join([module, *parts[:-1]]), parts[-1])


def check(root, groups, known_defects):
    problems = []
    counts = {}
    for i in range(1, groups + 1):
        files = glob.glob(os.path.join(root, "**", "counts-%d.json" % i), recursive=True)
        if len(files) != 1:
            problems.append("group %d: expected one accounting file, found %d" % (i, len(files)))
            continue
        counts[i] = json.load(open(files[0], encoding="utf-8"))
        junit = glob.glob(os.path.join(root, "**", "junit-%d.xml" % i), recursive=True)
        if len(junit) != 1:
            problems.append("group %d: missing JUnit" % i)
            continue
        reported = junit_ids(junit[0])
        missing = [n for n in counts[i]["selected"] if as_junit(n) not in reported]
        if missing:
            problems.append("group %d: %d selected nodes absent from JUnit, e.g. %s" % (i, len(missing), missing[:3]))
        if not counts[i]["selected"]:
            problems.append("group %d selected no test" % i)
    if problems:
        return problems
    digests = {c["collected_digest"] for c in counts.values()}
    totals = {c["collected"] for c in counts.values()}
    if len(digests) != 1 or len(totals) != 1:
        return ["groups collected different node sets: %s" % sorted(totals)]
    total = totals.pop()
    seen = {}
    for i, c in counts.items():
        for n in c["selected"]:
            if n in seen:
                problems.append("node %s ran in groups %d and %d" % (n, seen[n], i))
            seen[n] = i
    if set(seen) & known_defects:
        problems.append("a known defect ran in a required group: %s" % sorted(set(seen) & known_defects)[:3])
    if len(seen) + len(known_defects) != total:
        problems.append("groups selected %d + %d known defects != %d collected" % (len(seen), len(known_defects), total))
    if not problems:
        print("groups ok: %d collected = %d executed + %d known defects, %d groups" % (total, len(seen), len(known_defects), groups))
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--groups", type=int, required=True)
    ap.add_argument("--known-defects", required=True)
    a = ap.parse_args(argv)
    problems = check(a.root, a.groups, known(a.known_defects))
    for p in problems:
        print("GROUP CHECK FAILED:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
