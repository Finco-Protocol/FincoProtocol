"""Fully synthetic P0-B3 tests: no imported private reference data or engine runs."""
from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from tools.numerical_validation import (
    CATEGORIES, Manifest, ReconciliationInputError, canonical_bytes, compare,
    reports, sha256_bytes,
)
from tools.numerical_validation import oracles
from tools.numerical_validation.__main__ import _private_output, run_cli

HASH = "a" * 64
CONVENTIONS = "b" * 64
CONFIG = "c" * 64
START, END = "2030-01-01", "2031-01-01"


def make_fixture(*, source_value="100", finco_value="100", source_metric="gross_revenue",
                 finco_metric="total_revenue", stage="revenue"):
    reference = {"rows": [{"metric": source_metric, "period": "ref-y1", "value": source_value,
                           "unit": "kEUR", "currency": "EUR"}]}
    finco = {"rows": [{"metric": finco_metric, "period": "finco-y1", "value": finco_value,
                       "unit": "kEUR", "currency": "EUR"}]}
    source_data = canonical_bytes(reference)
    finco_data = canonical_bytes(finco)

    def identity(run, version, sha):
        return {"project_key": "synthetic-project", "scenario_key": "base-case",
                "configuration_sha256": CONFIG, "run_key": run,
                "calculated_at": "2031-02-01T00:00:00Z",
                "engine_version": version, "output_sha256": sha, "currency": "EUR",
                "calendar": "calendar-year", "conventions_sha256": CONVENTIONS}

    manifest = {
        "version": 1,
        "reference": identity("ref-synthetic-1", "synthetic-v1", sha256_bytes(source_data)),
        "finco": identity("finco-synthetic-1", "synthetic-finco-v1", sha256_bytes(finco_data)),
        "reference_export_version": "synthetic-v1",
        "reference_parsed_version": "synthetic-v1",
        "periods": [{"reference": {"key": "ref-y1", "start": START, "end": END},
                     "finco": {"key": "finco-y1", "start": START, "end": END}}],
        "metrics": [{"key": "revenue", "stage": stage,
                     "reference_metric": source_metric, "finco_metric": finco_metric,
                     "unit": "kEUR", "abs_tolerance": "0.01", "rel_tolerance": "0.0001"}],
    }
    return manifest, source_data, finco_data


def result(m, a, b):
    return compare(m, a, b)


def test_exact_match_and_evidence_hashes_are_reproducible():
    m, a, b = make_fixture()
    out = result(m, a, b)
    assert out["counts"] == {"PASS": 1, "FAIL": 0, "UNAVAILABLE": 0, "NOT_COMPARABLE": 0}
    assert out["identity"]["reference_sha256"] == sha256_bytes(a)
    assert out["first_material_divergence"] is None
    assert out == result(m, a, b)


def test_delta_is_finco_minus_reference_and_first_divergence():
    m, a, b = make_fixture(finco_value="105")
    out = result(m, a, b)
    row = out["results"][0]
    assert row["status"] == "FAIL"
    assert row["delta_finco_minus_reference"] == "5"
    assert row["absolute_difference"] == "5"
    assert out["first_material_divergence"]["stage"] == "revenue"
    assert out["first_material_divergence"]["classification"] == "UPSTREAM_DIFFERENCE_REQUIRES_INVESTIGATION"
    assert "DEFECT" not in json.dumps(out)


@pytest.mark.parametrize("source,finco,verdict", [
    ("100", "100.009", "PASS"), ("100", "100.011", "FAIL"),
    ("0", "0", "PASS"), ("0", "0.001", "PASS"), ("0", "0.011", "FAIL"),
])
def test_explicit_absolute_tolerance_and_zero_semantics(source, finco, verdict):
    m, a, b = make_fixture(source_value=source, finco_value=finco)
    assert result(m, a, b)["results"][0]["status"] == verdict


def test_relative_tolerance_uses_max_abs_scale_and_not_downstream_fit():
    m, a, b = make_fixture(source_value="100000", finco_value="100005")
    row = result(m, a, b)["results"][0]
    assert row["status"] == "PASS" and Decimal(row["tolerance_allowance"]) > 10
    m["metrics"][0]["rel_tolerance"] = "0"
    assert result(m, a, b)["results"][0]["status"] == "FAIL"


@pytest.mark.parametrize("value", [None, ""])
def test_missing_value_is_not_zero(value):
    m, a, b = make_fixture(source_value=value)
    if value == "":
        # Empty string is not a missing observation: malformed numerical evidence is rejected.
        with pytest.raises(ReconciliationInputError):
            result(m, a, b)
    else:
        row = result(m, a, b)["results"][0]
        assert row["status"] == "UNAVAILABLE"
        assert row["reference_value"] is None
        assert row["delta_finco_minus_reference"] is None


def test_missing_metric_row_is_unavailable_and_does_not_assume_zero():
    m, a, b = make_fixture()
    doc = {"rows": []}
    b = canonical_bytes(doc)
    m["finco"]["output_sha256"] = sha256_bytes(b)
    row = result(m, a, b)["results"][0]
    assert row["status"] == "UNAVAILABLE" and row["finco_value"] is None


@pytest.mark.parametrize("field", ["project_key", "scenario_key", "configuration_sha256"])
def test_incorrect_project_scenario_or_configuration_is_rejected(field):
    m, a, b = make_fixture()
    m["finco"][field] = HASH if field.endswith("sha256") else "different"
    with pytest.raises(ReconciliationInputError, match="project/scenario/configuration mismatch"):
        result(m, a, b)


@pytest.mark.parametrize("side", ["reference", "finco"])
def test_invalid_evidence_digest_is_rejected(side):
    m, a, b = make_fixture()
    m[side]["output_sha256"] = "0" * 64
    with pytest.raises(ReconciliationInputError, match="evidence SHA mismatch"):
        result(m, a, b)


def test_export_parsed_source_version_conflict_blocks_all_metrics_without_fake_parity():
    m, a, b = make_fixture()
    m["reference_parsed_version"] = "synthetic-v2"
    out = result(m, a, b)
    assert out["counts"]["NOT_COMPARABLE"] == 1
    assert "SOURCE_ENGINE_VERSION_CONFLICT" in out["provenance_blockers"]
    assert out["results"][0]["delta_finco_minus_reference"] is None


def test_source_export_does_not_match_manifest_engine_blocks():
    m, a, b = make_fixture()
    m["reference_export_version"] = "synthetic-v2"
    out = result(m, a, b)
    assert "REFERENCE_ENGINE_NOT_ATTESTED" in out["provenance_blockers"]


@pytest.mark.parametrize("field", ["currency", "calendar", "conventions_sha256"])
def test_currency_calendar_and_conventions_require_explicit_reconciliation(field):
    m, a, b = make_fixture()
    m["finco"][field] = {"currency": "USD", "calendar": "fiscal", "conventions_sha256": HASH}[field]
    out = result(m, a, b)
    assert out["counts"]["NOT_COMPARABLE"] == 1
    assert out["results"][0]["delta_finco_minus_reference"] is None


def test_period_mismatch_is_not_automatically_prorated():
    m, a, b = make_fixture()
    m["periods"][0]["finco"]["end"] = "2030-12-31"
    row = result(m, a, b)["results"][0]
    assert row["status"] == "NOT_COMPARABLE" and row["reason"] == "PERIOD_AXIS_MISMATCH"


@pytest.mark.parametrize("case", ["source_unit", "finco_unit", "observation_currency"])
def test_observation_unit_or_currency_mismatch_requires_normalization(case):
    m, a, b = make_fixture()
    doc = json.loads(a)
    if case == "source_unit":
        doc["rows"][0]["unit"] = "EUR"
    elif case == "observation_currency":
        doc["rows"][0]["currency"] = "USD"
    else:
        doc = json.loads(b)
        doc["rows"][0]["unit"] = "EUR"
    raw = canonical_bytes(doc)
    if case == "finco_unit":
        b = raw
        m["finco"]["output_sha256"] = sha256_bytes(raw)
    else:
        a = raw
        m["reference"]["output_sha256"] = sha256_bytes(raw)
    row = result(m, a, b)["results"][0]
    assert row["status"] == "NOT_COMPARABLE" and row["delta_finco_minus_reference"] is None


def test_duplicate_evidence_ids_and_duplicate_mappings_rejected():
    m, a, b = make_fixture()
    doc = json.loads(a)
    doc["rows"].append(copy.deepcopy(doc["rows"][0]))
    a = canonical_bytes(doc)
    m["reference"]["output_sha256"] = sha256_bytes(a)
    with pytest.raises(ReconciliationInputError, match="duplicate output identity"):
        result(m, a, b)
    m, a, b = make_fixture()
    m["metrics"].append(copy.deepcopy(m["metrics"][0]))
    with pytest.raises(ReconciliationInputError, match="duplicate mapping identity"):
        result(m, a, b)
    m, a, b = make_fixture()
    m["periods"].append(copy.deepcopy(m["periods"][0]))
    with pytest.raises(ReconciliationInputError, match="duplicate mapping identity"):
        result(m, a, b)


@pytest.mark.parametrize("mutate", [
    lambda m: m.update(version=2),
    lambda m: m["reference"].update(calculated_at="2031-02-01"),
    lambda m: m["metrics"][0].update(abs_tolerance="-1"),
    lambda m: m["metrics"][0].update(rel_tolerance="NaN"),
    lambda m: m["metrics"][0].update(stage="invented_stage"),
    lambda m: m["periods"][0]["reference"].update(start="2032-01-01"),
    lambda m: m["reference"].update(run_key=""),
    lambda m: m.update(new_unsupported_field=123),
])
def test_malformed_manifest_fails_closed(mutate):
    m, a, b = make_fixture()
    mutate(m)
    with pytest.raises(ReconciliationInputError):
        result(m, a, b)


def test_untrusted_extra_evidence_fields_are_rejected():
    m, a, b = make_fixture()
    doc = json.loads(a)
    doc["rows"][0]["extra"] = "untrusted"
    a = canonical_bytes(doc)
    m["reference"]["output_sha256"] = sha256_bytes(a)
    with pytest.raises(ReconciliationInputError):
        result(m, a, b)


def test_deterministic_json_csv_and_markdown():
    m, a, b = make_fixture(finco_value="101")
    out = result(m, a, b)
    one, two = reports(out), reports(out)
    assert one == two and set(one) == {"report.json", "report.csv", "report.md"}
    assert b"FINCO - reference" in one["report.md"]
    assert b"OUTSIDE_APPROVED_TOLERANCE" in one["report.csv"]
    assert json.loads(one["report.json"])["counts"]["FAIL"] == 1


def test_earliest_stage_not_largest_downstream_residual():
    m, a, b = make_fixture(source_value="100", finco_value="101")
    for stage in ("returns", "generation", "tax"):
        ref_id, finco_id = "s_" + stage, "f_" + stage
        m["metrics"].append({
            "key": stage, "stage": stage, "reference_metric": ref_id,
            "finco_metric": finco_id, "unit": "kEUR", "abs_tolerance": "0", "rel_tolerance": "0"
        })
        reference = json.loads(a)
        finco = json.loads(b)
        reference["rows"].append({"metric": ref_id, "period": "ref-y1",
                                   "value": "100", "unit": "kEUR", "currency": "EUR"})
        finco["rows"].append({"metric": finco_id, "period": "finco-y1",
                               "value": "1000" if stage == "returns" else "101",
                               "unit": "kEUR", "currency": "EUR"})
        a, b = canonical_bytes(reference), canonical_bytes(finco)
    m["reference"]["output_sha256"] = sha256_bytes(a)
    m["finco"]["output_sha256"] = sha256_bytes(b)
    assert result(m, a, b)["first_material_divergence"]["stage"] == "generation"


def test_bounded_independent_oracles_and_signed_residuals():
    assert oracles.revenue("100", "50", "5", tolerance_keur="0").status == "PASS"
    assert oracles.revenue("100", "50", "4.9", tolerance_keur=".01").status == "FAIL"
    assert oracles.allocation([".45", ".45", ".10"], tolerance=0).status == "PASS"
    assert oracles.debt_rollforward("100", "20", "15", "105", tolerance=0).status == "PASS"
    assert oracles.interest("100", ".05", "30", "360", "0.4166666666666666666666666667",
                            tolerance="0.00000001").status == "PASS"
    assert oracles.sources_uses("150", "150", tolerance=0).status == "PASS"
    assert oracles.cash_conservation("50", "20", "15", "55", tolerance=0).status == "PASS"
    assert oracles.balance_sheet("300", "200", "100", tolerance=0).status == "PASS"
    assert oracles.discounted_cashflows(["100", "100"], ["1", ".9"], "190", tolerance=0).status == "PASS"


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-1"])
def test_oracle_rejects_invalid_share_inputs(bad):
    with pytest.raises(ReconciliationInputError):
        oracles.allocation([".5", bad], tolerance=0)


def test_cli_writes_private_reports_and_uses_nonzero_for_failed_comparison(tmp_path, capsys):
    m, a, b = make_fixture(finco_value="101")
    for name, value in [("manifest.json", canonical_bytes(m)),
                        ("source.json", a), ("finco.json", b)]:
        (tmp_path / name).write_bytes(value)
    argv = ["--authorized-source", "--manifest", str(tmp_path / "manifest.json"),
            "--reference", str(tmp_path / "source.json"), "--finco", str(tmp_path / "finco.json"),
            "--output", str(tmp_path / "private-output")]
    assert run_cli(argv) == 2
    assert (tmp_path / "private-output" / "report.json").exists()
    assert (tmp_path / "private-output" / "report.csv").exists()
    assert (tmp_path / "private-output" / "report.md").exists()
    assert "OUTSIDE_APPROVED_TOLERANCE" not in capsys.readouterr().out
    assert run_cli(argv[1:]) != 0  # missing signed-off authorised-source acknowledgement



@pytest.mark.parametrize("anchor,duplicate,source_identity", [
    ('"abs_tolerance":"0.01"', '"abs_tolerance":"999"', False),
    ('"rel_tolerance":"0.0001"', '"rel_tolerance":"999"', False),
    ('"engine_version":"synthetic-v1"', '"engine_version":"spoofed-v2"', False),
    ('"configuration_sha256":"' + CONFIG + '"',
     '"configuration_sha256":"' + HASH + '"', True),
    ('"version":1', '"version":2', False),
])
def test_cli_rejects_duplicate_manifest_json_keys_at_all_levels(
        tmp_path, capsys, anchor, duplicate, source_identity):
    """Fail before comparison/report creation, even when the first value is valid.

    Tolerance, source engine provenance, normalized configuration identity, and
    root manifest version keys are tested through the real CLI entry point.
    """
    manifest, source_data, finco_data = make_fixture()
    raw = canonical_bytes(manifest).decode("utf-8")
    assert anchor in raw
    if source_identity:
        # Reference is the final occurrence after FINCO in sorted JSON.
        before, sep, after = raw.rpartition(anchor)
        assert sep
        raw = before + sep + "," + duplicate + after
    else:
        raw = raw.replace(anchor, anchor + "," + duplicate, 1)
    (tmp_path / "manifest.json").write_text(raw, encoding="utf-8")
    (tmp_path / "source.json").write_bytes(source_data)
    (tmp_path / "finco.json").write_bytes(finco_data)
    outdir = tmp_path / "private-reports"
    rc = run_cli([
        "--authorized-source",
        "--manifest", str(tmp_path / "manifest.json"),
        "--reference", str(tmp_path / "source.json"),
        "--finco", str(tmp_path / "finco.json"),
        "--output", str(outdir),
    ])
    captured = capsys.readouterr()
    assert rc == 3
    assert "RECONCILIATION_BLOCKED" in captured.err
    assert "duplicate JSON object key" in captured.err
    assert "NUMERICAL_COMPARISON_PRODUCED" not in captured.out
    assert not outdir.exists()

def test_cli_rejects_unignored_repo_path():
    with pytest.raises(ReconciliationInputError, match="PRIVATE_OUTPUT_ONLY"):
        _private_output(Path(__file__).resolve().parents[1] / "docs" / "accidentally-public")


def test_numerical_validation_import_does_not_load_engine():
    source = (Path(__file__).resolve().parents[1] / "tools/numerical_validation/reconcile.py").read_text()
    assert "from financial_engine" not in source and "from finco_core" not in source
    assert "run_clean_production" not in source
