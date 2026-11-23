"""UX-FINAL-01 behavioural contract (integrated from #446 by FINCO 34 batch 1).

Keeps the non-governance assertions of the historical #446 scope module (whose exact-source / cohort / clone-tamper
machinery was retired by the CI normalization, #476) in an active location:

* the Financing read-layer node suites (pr3b1: readLayer, debtProvenance, uxFinal01) actually execute -- they were
  previously only executed through the archived ux_pr3b1 / f03 / f04 scope helpers;
* NOT_RUN stays a distinct gate that withholds Run values and does not repeat the raw state code;
* the living screen contract uses one closed status vocabulary (an over-claim such as PASS/DONE is refused).
"""
from __future__ import annotations

import csv
import io
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PR3B1_SUITES = sorted((ROOT / "frontend/src/app/financing/pr3b1/__tests__").glob("*.test.mjs"))


@pytest.mark.parametrize("suite", PR3B1_SUITES, ids=[p.name for p in PR3B1_SUITES])
def test_financing_read_layer_node_suites_pass(suite):
    assert (ROOT / "frontend/node_modules/esbuild").is_dir(), "frontend node_modules (npm ci) is required"
    proc = subprocess.run(["node", "--test", str(suite)], cwd=ROOT, capture_output=True, text=True, timeout=600)
    tail = (proc.stdout + proc.stderr)[-4000:]
    assert proc.returncode == 0, tail
    assert re.search(r"^# fail 0$", proc.stdout, re.M), tail
    assert int(re.search(r"^# pass (\d+)$", proc.stdout, re.M).group(1)) > 0, tail


def test_the_three_read_layer_suites_are_present():
    assert {p.name for p in PR3B1_SUITES} >= {"readLayer.test.mjs", "debtProvenance.test.mjs", "uxFinal01.test.mjs"}


def test_not_run_stays_a_distinct_gate_with_no_run_values():
    text = (ROOT / "frontend/src/app/financing/pr3b1/runEvidence.ts").read_text(encoding="utf-8")
    m = re.search(r"return \{state:'NOT_RUN',showRun:false,reason:'([^']+)',assurance:'NOT_PROVEN'\}", text)
    assert m, "the NOT_RUN gate must keep state NOT_RUN, showRun false and NOT_PROVEN assurance"
    assert m.group(1).startswith("No committed Run for this project yet.") and "NOT_RUN" not in m.group(1)
    assert "never zero" in m.group(1)


CONTRACT = ROOT / "docs/react_migration/ux_final01/screen_contract.csv"
CONTRACT_HEADER = ["screen", "status", "workstream", "acceptance", "source_path", "note"]
CLOSED_STATUSES = frozenset(("CURRENT", "CODED", "BROWSER_VERIFIED", "SOURCE_BYTE_INTEGRATED", "HOSTED_CI_VERIFIED", "PARTIAL",
                             "DEPENDENCY_PENDING", "BLOCKED", "DO_NOT_CHANGE", "MISSING"))


def contract_problems(text):
    """Every structural or vocabulary problem of a screen contract (empty list = valid)."""
    problems = []
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or rows[0] != CONTRACT_HEADER:
        return ["header is not exactly " + ",".join(CONTRACT_HEADER)]
    seen = set()
    for n, row in enumerate(rows[1:], 2):
        if len(row) != len(CONTRACT_HEADER):
            problems.append("row %d has %d columns" % (n, len(row)))
            continue
        screen, status = row[0], row[1]
        if not screen.strip() or screen != screen.strip():
            problems.append("row %d screen is empty or padded" % n)
        if status not in CLOSED_STATUSES:
            problems.append("row %d status %r is outside the closed vocabulary" % (n, status))
        if screen in seen:
            problems.append("row %d duplicates screen %r" % (n, screen))
        seen.add(screen)
    return problems


def test_the_screen_contract_is_valid_and_keeps_its_honest_open_states():
    text = CONTRACT.read_text(encoding="utf-8")
    assert contract_problems(text) == []
    used = {r[1] for r in csv.reader(io.StringIO(text))} - {"status"}
    assert "PARTIAL" in used and "DEPENDENCY_PENDING" in used
    assert not used & {"PASS", "DONE", "COMPLETE", "IMPLEMENTED"}
    # Source paths named by the contract exist in the checkout (no row points at a retired/removed file).
    for row in list(csv.reader(io.StringIO(text)))[1:]:
        assert (ROOT / row[4]).exists(), row[4]


@pytest.mark.parametrize("bad", ["PASS", "DONE", "COMPLETE", "IMPLEMENTED", "partial", "PARTIAL ", "", "CURRENT|CODED"])
def test_the_status_validator_rejects_anything_outside_the_closed_vocabulary(bad):
    good = ",".join(CONTRACT_HEADER) + "\nscreen one,PARTIAL,UX-01,AC-01,path,note\n"
    assert contract_problems(good) == []
    assert contract_problems(",".join(CONTRACT_HEADER) + "\nscreen one,%s,UX-01,AC-01,path,note\n" % bad), bad


def test_the_contract_validator_rejects_structural_forgeries():
    h = ",".join(CONTRACT_HEADER)
    assert contract_problems("screen,status\nx,PARTIAL\n")
    assert contract_problems(h + "\nonly,PARTIAL,UX-01\n")
    assert contract_problems(h + "\ndup,PARTIAL,a,b,c,d\ndup,CURRENT,a,b,c,d\n")
    assert contract_problems(h + "\n ,PARTIAL,a,b,c,d\n")
    assert contract_problems("")
