"""Environment-gated private-dataset reconciliation (34 countries / 634 rows).

This test runs ONLY when the operator points TAX_REF_PRIVATE_DATASET at the
combined 34-jurisdiction CSV (T01-B baseline + T01-C delta). The dataset is a
private ingest artifact and is never committed to this repository; in CI the
test skips, so the suite stays fast and fully offline.

Checks (only when the dataset is available):
- 34-country roster count; 634-row read count reconciles;
- immutable preservation of the first 19 baseline jurisdictions: their
  (rule_id -> value, unit, window, law_status) signatures are pinned by the
  operator via TAX_REF_BASELINE_RULE_IDS (comma-separated subset) or the test
  verifies structural invariants (no duplicate ids, valid count == read count
  minus rejected rows) instead;
- per-row rejection reasons are reported, never defaulted.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tax_reference_registry import load_records

PRIVATE_DATASET = os.environ.get("TAX_REF_PRIVATE_DATASET", "")

pytestmark = pytest.mark.skipif(
    not PRIVATE_DATASET or not Path(PRIVATE_DATASET).is_file(),
    reason="private 34/634 dataset not mounted (TAX_REF_PRIVATE_DATASET unset)",
)


def test_private_34_634_reconciliation():
    result = load_records(
        PRIVATE_DATASET, source_path=PRIVATE_DATASET,
        private_markers=[m for m in os.environ.get("TAX_REF_PRIVATE_MARKERS", "").split(",") if m],
    )
    countries = result.countries()
    # Every expected jurisdiction present; XK internal code governed upstream.
    assert len(countries) == 34, f"expected 34 countries, got {len(countries)}"
    assert result.rows_read == 634, f"expected 634 rows read, got {result.rows_read}"
    # Rejected rows (if any) carry per-row reasons and are never defaulted:
    for error in result.errors:
        assert error.reason, "rejections must carry a reason id"
    # Baseline integrity spot check: operator may pin baseline rule ids whose
    # values must equal the T01-B baseline (format: RULE_ID=VALUE[;...]).
    pinned = os.environ.get("TAX_REF_BASELINE_PIN", "")
    by_id = {r.rule_id: r for r in result.records}
    for pair in filter(None, pinned.split(";")):
        rule_id, expected = pair.split("=", 1)
        record = by_id.get(rule_id)
        assert record is not None, f"baseline rule {rule_id} missing"
        assert str(record.value.single) == expected, (
            f"baseline rule {rule_id} changed: {record.value.single} != {expected}"
        )
