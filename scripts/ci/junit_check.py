"""Fail unless a JUnit file has the expected number of test cases and every one passed (no skip, failure or error)."""
import argparse
import sys
import xml.etree.ElementTree as ET


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("junit")
    ap.add_argument("--exact", type=int, help="required number of test cases")
    a = ap.parse_args(argv)
    cases = list(ET.parse(a.junit).getroot().iter("testcase"))
    bad = [c.get("classname", "") + "::" + c.get("name", "") for c in cases
           if any(c.find(tag) is not None for tag in ("skipped", "failure", "error"))]
    if not cases or bad or (a.exact is not None and len(cases) != a.exact):
        print("JUNIT CHECK FAILED: %d cases (expected %s), not passed: %s" % (len(cases), a.exact, bad))
        return 1
    print("junit ok: %d cases, all passed" % len(cases))
    return 0


if __name__ == "__main__":
    sys.exit(main())
