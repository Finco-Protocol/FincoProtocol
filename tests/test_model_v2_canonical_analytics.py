"""Workflow 06 - Canonical Analytics acceptance matrix.

Acceptance markers:

  CANONICAL_ANALYTICS_PASS_THROUGH       exact verbatim authority values
  CANONICAL_ANALYTICS_ZERO_OR_MISSING    0.0 stays AVAILABLE; None never 0
  CANONICAL_ANALYTICS_RUN_BOUND          run identity required and binding
  CANONICAL_ANALYTICS_WC_VS_LAST_RUN     draft edits never rewrite history
  CANONICAL_ANALYTICS_FAILED_RUN         failure produces no snapshot
  CANONICAL_ANALYTICS_DETERMINISM        same run -> byte-identical payload
  CANONICAL_ANALYTICS_NO_RECOMPUTE       no finance math in the layer
  CANONICAL_ANALYTICS_TRACE_ALIGNMENT    analytics == trace verbatim
  CANONICAL_ANALYTICS_SOLAR_REFERENCE    protected solar proof
  CANONICAL_ANALYTICS_WIND_REFERENCE     protected wind proof
  CANONICAL_ANALYTICS_FUTURE_SEAMS       WACC/payback/etc honestly missing
"""
from __future__ import annotations

import ast
from dataclasses import replace as dc_replace

import pytest

from app.model_v2.assumption_register import (
    AssumptionSourceKind,
    RegisterContext,
    RunIdentity,
)
from app.model_v2.calculation_trace import build_calculation_trace
from app.model_v2.canonical_analytics import (
    CanonicalAnalyticsSnapshot,
    CanonicalMetricStatus,
    build_canonical_analytics,
)
from app.project_factories import (
    create_generic_solar_reference,
    create_generic_wind_reference,
)
from app.services.clean_presentation_adapter import build_clean_waterfall_view
from app.services.production_financial_authority import (
    CleanProductionRunUnavailable,
    run_clean_production,
)


def _identity(snapshot_id="W06-A", scenario_id="Base"):
    return RunIdentity(
        snapshot_id=snapshot_id,
        composite_hash="hash-" + snapshot_id,
        workbook_version="2.3.0",
        engine_version="clean_senior_debt_v0",
        scenario_id=scenario_id,
    )


@pytest.fixture(scope="module")
def solar():
    inputs = create_generic_solar_reference()
    run = run_clean_production(inputs, "Base", project_type="solar")
    snapshot = build_canonical_analytics(run, run_identity=_identity())
    return inputs, run, snapshot


@pytest.fixture(scope="module")
def wind():
    inputs = create_generic_wind_reference()
    run = run_clean_production(inputs, "Base", project_type="wind")
    snapshot = build_canonical_analytics(run, run_identity=_identity("W06-W"))
    return inputs, run, snapshot


# ---------------------------------------------------------------------------
# PASS-THROUGH
# ---------------------------------------------------------------------------


def test_pass_through_is_bit_exact(solar):
    """CANONICAL_ANALYTICS_PASS_THROUGH = PASS."""
    _, run, snapshot = solar
    g2c = run.g2c_result
    assert snapshot.metric("project_xirr").value == (
        g2c.return_summary.project.project_xirr
    )
    assert snapshot.metric("pure_equity_xirr").value == g2c.pure_equity_xirr
    assert snapshot.metric("pure_equity_moic").value == g2c.pure_equity_moic
    assert snapshot.metric("total_sponsor_xirr").value == g2c.total_sponsor_xirr
    assert snapshot.metric("total_sponsor_moic").value == g2c.total_sponsor_moic
    assert snapshot.metric("senior_debt_keur").value == (
        g2c.financing_result.final_senior_commitment_keur
    )
    view = build_clean_waterfall_view(run)
    assert snapshot.metric("min_dscr").value == view.actual_min_dscr
    assert snapshot.metric("total_revenue_keur").value == view.total_revenue_keur
    assert snapshot.metric("total_ebitda_keur").value == view.total_ebitda_keur


def test_units_are_machine_semantic(solar):
    """XIRR fraction, MOIC multiple, money kEUR, coverage ratio."""
    _, _, snapshot = solar
    assert snapshot.metric("project_xirr").unit == "fraction"
    assert snapshot.metric("pure_equity_moic").unit == "multiple"
    assert snapshot.metric("senior_debt_keur").unit == "kEUR"
    assert snapshot.metric("min_dscr").unit == "ratio"
    assert snapshot.metric("total_revenue_keur").unit == "kEUR"
    # raw fractions are never percent-converted for display
    assert snapshot.metric("project_xirr").value < 1.0


# ---------------------------------------------------------------------------
# ZERO / MISSING
# ---------------------------------------------------------------------------


def test_zero_stays_available_and_none_stays_missing(solar):
    """CANONICAL_ANALYTICS_ZERO_OR_MISSING = PASS."""
    _, _, snapshot = solar
    unavailable = snapshot.metric("min_llcr")
    assert unavailable.value is None
    assert unavailable.status is CanonicalMetricStatus.UNAVAILABLE
    assert unavailable.source_status == "COVERAGE_CFADS_CASE_NOT_CONFIGURED"
    assert unavailable.value != 0.0
    npv = snapshot.metric("project_npv_keur")
    assert npv.value is None
    assert npv.status is CanonicalMetricStatus.UNAVAILABLE
    # a legitimate economic zero would serialize as AVAILABLE 0.0 - proven
    # at the contract layer:
    payload = {
        "metric_id": "m", "category": "OPERATING", "value": 0.0,
        "unit": "kEUR", "status": "AVAILABLE", "source_status": None,
        "source_authority": "t", "methodology_ref": None,
        "trace_ref": None, "notes": None,
    }
    from app.model_v2.canonical_analytics import _metric_from_dict

    zero = _metric_from_dict(payload)
    assert zero.value == 0.0
    assert zero.status is CanonicalMetricStatus.AVAILABLE
    # value-bearing metrics must be AVAILABLE; None+UNAVAILABLE is legal
    with pytest.raises(ValueError, match="only AVAILABLE"):
        _metric_from_dict({**payload, "value": 5.0, "status": "UNAVAILABLE"})
    none_unavailable = _metric_from_dict(
        {**payload, "value": None, "status": "UNAVAILABLE"}
    )
    assert none_unavailable.value is None
    with pytest.raises(ValueError, match="AVAILABLE without a value"):
        _metric_from_dict({**payload, "value": None})


def test_not_applicable_distinct_from_unavailable(solar):
    """NOT_APPLICABLE is its own status, never UNAVAILABLE-0."""
    _, _, snapshot = solar
    for metric in snapshot.metrics:
        if metric.source_status and "NOT_APPLICABLE" in metric.source_status:
            assert metric.status is CanonicalMetricStatus.NOT_APPLICABLE
            assert metric.value is None
    # future seams are AUTHORITY_MISSING, a fourth distinct state
    lcoe = snapshot.metric("lcoe")
    assert lcoe.status is CanonicalMetricStatus.AUTHORITY_MISSING
    assert lcoe.value is None


# ---------------------------------------------------------------------------
# RUN IDENTITY / WORKING COPY VS LAST RUN
# ---------------------------------------------------------------------------


def test_run_bound_only(solar):
    """CANONICAL_ANALYTICS_RUN_BOUND = PASS."""
    _, run, snapshot = solar
    with pytest.raises(ValueError, match="ANALYTICS_RUN_IDENTITY_REQUIRED"):
        build_canonical_analytics(run, run_identity=None)  # type: ignore[arg-type]
    assert snapshot.run_identity.snapshot_id == "W06-A"
    assert snapshot.engine_version == "clean_senior_debt_v0"
    assert snapshot.workbook_version == "2.3.0"
    identity = _identity()
    trace = build_calculation_trace(
        run,
        context=RegisterContext.for_run_bound(
            run_identity=identity,
            state_provenance=AssumptionSourceKind.UNKNOWN,
        ),
    )
    assert build_canonical_analytics(
        run, run_identity=identity, trace=trace
    ).to_json() == snapshot.to_json()
    other = _identity("W06-OTHER")
    with pytest.raises(ValueError, match="ANALYTICS_TRACE_IDENTITY_MISMATCH"):
        build_canonical_analytics(run, run_identity=other, trace=trace)
    wc_trace = build_calculation_trace(
        run,
        context=RegisterContext.for_working_copy(
            state_provenance=AssumptionSourceKind.UNKNOWN
        ),
    )
    with pytest.raises(ValueError, match="ANALYTICS_TRACE_CONTEXT_MISMATCH"):
        build_canonical_analytics(run, run_identity=identity, trace=wc_trace)


def test_working_copy_edit_never_rewrites_history(solar):
    """CANONICAL_ANALYTICS_WC_VS_LAST_RUN = PASS."""
    inputs, run, snapshot = solar
    before = snapshot.to_json()
    edited = dc_replace(
        inputs, technical=dc_replace(inputs.technical, capacity_mw=99.0)
    )
    later_run = run_clean_production(edited, "Base", project_type="solar")
    later_snapshot = build_canonical_analytics(
        later_run, run_identity=_identity("W06-LATER")
    )
    assert snapshot.to_json() == before
    assert snapshot.metric("senior_debt_keur").value != (
        later_snapshot.metric("senior_debt_keur").value
    )
    assert snapshot.run_identity != later_snapshot.run_identity


def test_scenario_identity_remains_distinct(solar):
    """CANONICAL_ANALYTICS_RUN_BOUND + CORRECTION A1: scenario ids never
    blend; a contradictory scenario identity fails closed."""
    inputs, run, _snapshot = solar
    # same Base run, canonical token matches: accepted
    base = build_canonical_analytics(run, run_identity=_identity())
    assert base.scenario == "Base"
    assert base.run_identity.scenario_id == "Base"
    # same Base run wrapped as a different scenario: FAIL CLOSED
    with pytest.raises(ValueError, match="ANALYTICS_SCENARIO_IDENTITY_MISMATCH"):
        build_canonical_analytics(
            run, run_identity=_identity("W06-DOWN", scenario_id="Downside")
        )
    # genuine non-Base canonical run: matching identity accepted
    downside_run = run_clean_production(inputs, "Downside", project_type="solar")
    downside = build_canonical_analytics(
        downside_run, run_identity=_identity("W06-DOWN2", scenario_id="Downside")
    )
    assert downside.scenario == "Downside"
    assert downside.to_json() != base.to_json()
    # and the reverse wrap fails closed too
    with pytest.raises(ValueError, match="ANALYTICS_SCENARIO_IDENTITY_MISMATCH"):
        build_canonical_analytics(
            downside_run, run_identity=_identity("W06-BASE2", scenario_id="Base")
        )


def test_failed_run_cannot_replace_snapshot(solar):
    """CANONICAL_ANALYTICS_FAILED_RUN = PASS."""
    inputs, _run, snapshot = solar
    not_ready = dc_replace(
        inputs,
        tax=dc_replace(inputs.tax, clean_cash_tax_timing_enabled=False),
    )
    with pytest.raises(CleanProductionRunUnavailable):
        run_clean_production(not_ready, "Base", project_type="solar")
    # no snapshot can exist for the failed run; prior snapshot untouched
    assert snapshot.metric("project_xirr").value is not None


# ---------------------------------------------------------------------------
# DETERMINISM + NO RECOMPUTATION
# ---------------------------------------------------------------------------


def test_determinism_and_presentation_independence(solar):
    """CANONICAL_ANALYTICS_DETERMINISM = PASS."""
    _, run, snapshot = solar
    again = build_canonical_analytics(run, run_identity=_identity())
    assert again.to_json() == snapshot.to_json()
    assert again.fingerprint == snapshot.fingerprint
    back = CanonicalAnalyticsSnapshot.from_json(snapshot.to_json())
    assert back.to_json() == snapshot.to_json()
    with pytest.raises(ValueError, match="SCHEMA_ID_MISMATCH"):
        CanonicalAnalyticsSnapshot.from_dict(
            {**snapshot.to_dict(), "schema_id": "x"}
        )
    with pytest.raises(ValueError, match="SCHEMA_VERSION_UNSUPPORTED"):
        CanonicalAnalyticsSnapshot.from_dict(
            {**snapshot.to_dict(), "schema_version": 42}
        )
    with pytest.raises(ValueError, match="unknown status"):
        broken = snapshot.to_dict()
        broken["metrics"][0]["status"] = "MOSTLY_AVAILABLE"
        CanonicalAnalyticsSnapshot.from_dict(broken)


def test_no_recomputation_in_production_layer():
    """CANONICAL_ANALYTICS_NO_RECOMPUTE = PASS - structural proof."""
    source = open(
        "app/model_v2/canonical_analytics.py", encoding="utf-8"
    ).read()
    tree = ast.parse(source)
    banned_names = {"sum", "min", "max", "npv", "irr", "xirr", "pow", "round"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in banned_names, node.func.id
        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)
        ):
            raise AssertionError(
                "arithmetic operator in production analytics layer at line "
                f"{node.lineno}"
            )
    # no engine execution imports in the production analytics layer
    # (the generated-from string is documentation, not a call)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(
                a.name.startswith(("app.services", "financial_engine"))
                for a in node.names
            )
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith(
                ("app.services", "financial_engine")
            ), node.module


def test_trace_alignment(solar):
    """CANONICAL_ANALYTICS_TRACE_ALIGNMENT = PASS."""
    _, run, snapshot = solar
    identity = _identity()
    trace = build_calculation_trace(
        run,
        context=RegisterContext.for_run_bound(
            run_identity=identity,
            state_provenance=AssumptionSourceKind.UNKNOWN,
        ),
    )
    for entry in trace.entries:
        metric = snapshot.metric(entry.output_key)
        assert metric.trace_ref == entry.output_key
        assert metric.value == entry.output_value
        assert metric.source_status == entry.status
        assert metric.source_authority == entry.authority
    # unavailable analytics remains unavailable in trace context
    assert snapshot.metric("min_llcr").status is CanonicalMetricStatus.UNAVAILABLE
    assert trace.entry("min_llcr").completeness.value == "UNAVAILABLE"


# ---------------------------------------------------------------------------
# SOLAR / WIND REFERENCE ACCEPTANCE
# ---------------------------------------------------------------------------


def test_solar_reference_proof(solar):
    """CANONICAL_ANALYTICS_SOLAR_REFERENCE = PASS."""
    inputs, run, snapshot = solar
    g2c = run.g2c_result
    assert snapshot.metric("project_xirr").value == (
        g2c.return_summary.project.project_xirr
    )
    assert snapshot.metric("project_xirr").value == pytest.approx(
        0.11768, abs=1e-5
    )
    assert snapshot.metric("senior_debt_keur").value == pytest.approx(
        26983.33, rel=1e-4
    )
    repeat = run_clean_production(inputs, "Base", project_type="solar")
    repeat_snapshot = build_canonical_analytics(
        repeat, run_identity=_identity()
    )
    assert repeat_snapshot.to_json() == snapshot.to_json()

def test_wind_reference_proof(wind):
    """CANONICAL_ANALYTICS_WIND_REFERENCE = PASS."""
    _inputs, run, snapshot = wind
    g2c = run.g2c_result
    assert snapshot.metric("project_xirr").value == (
        g2c.return_summary.project.project_xirr
    )
    assert snapshot.metric("project_xirr").value == pytest.approx(
        0.13311, abs=1e-5
    )
    assert snapshot.metric("senior_debt_keur").value == pytest.approx(
        36505.16, rel=1e-4
    )
    assert snapshot.metric("pure_equity_moic").value == g2c.pure_equity_moic
    assert snapshot.metric("total_sponsor_moic").value == (
        g2c.total_sponsor_moic
    )
    assert snapshot.run_identity.snapshot_id == "W06-W"


def test_future_metrics_honestly_unsupported(solar):
    """CANONICAL_ANALYTICS_FUTURE_SEAMS = PASS."""
    _, _, snapshot = solar
    for metric_id in ("lcoe", "wacc", "payback", "discounted_payback",
                      "cash_yield"):
        metric = snapshot.metric(metric_id)
        assert metric.status is CanonicalMetricStatus.AUTHORITY_MISSING
        assert metric.value is None
        assert metric.source_authority is None
    assert "no canonical LCOE authority" in snapshot.metric("lcoe").notes
    assert snapshot.metric("wacc").unit == "fraction"
    assert snapshot.metric("payback").unit == "years"
    assert snapshot.metric("discounted_payback").unit == "years"
    assert snapshot.metric("cash_yield").unit == "fraction"


# ---------------------------------------------------------------------------
# CORRECTION A: identity + manifest integrity
# ---------------------------------------------------------------------------


def test_a2_trace_version_contradiction_fails_closed(solar):
    """CORRECTION A2: supplied trace versions must match run identity."""
    import dataclasses

    inputs, run, _snapshot = solar
    identity = _identity()
    trace = build_calculation_trace(
        run,
        context=RegisterContext.for_run_bound(
            run_identity=identity,
            state_provenance=AssumptionSourceKind.UNKNOWN,
        ),
    )
    tampered = dataclasses.replace(trace, engine_version="engine-rogue-v1")
    with pytest.raises(ValueError, match="ANALYTICS_TRACE_VERSION_MISMATCH"):
        build_canonical_analytics(
            run, run_identity=identity, trace=tampered
        )
    tampered_workbook = dataclasses.replace(
        trace, workbook_version="9.9.9-rogue"
    )
    with pytest.raises(ValueError, match="ANALYTICS_TRACE_VERSION_MISMATCH"):
        build_canonical_analytics(
            run, run_identity=identity, trace=tampered_workbook
        )


def test_a3_deserialized_identity_contradiction_fails_closed(solar):
    """CORRECTION A3: serialized identity metadata must be self-consistent."""
    _, _, snapshot = solar
    payload = snapshot.to_dict()
    with pytest.raises(ValueError, match="ANALYTICS_IDENTITY_CONTRADICTION"):
        CanonicalAnalyticsSnapshot.from_dict(
            {**payload, "engine_version": "engine-rogue-v1"}
        )
    with pytest.raises(ValueError, match="ANALYTICS_IDENTITY_CONTRADICTION"):
        CanonicalAnalyticsSnapshot.from_dict(
            {**payload, "workbook_version": "9.9.9-rogue"}
        )
    with pytest.raises(
        ValueError, match="ANALYTICS_SCENARIO_IDENTITY_MISMATCH"
    ):
        CanonicalAnalyticsSnapshot.from_dict(
            {**payload, "scenario": "Downside"}
        )


def test_a4_metric_manifest_is_canonical(solar):
    """CORRECTION A4: schema v1 accepts only the canonical metric set."""
    _, _, snapshot = solar
    payload = snapshot.to_dict()
    metrics = payload["metrics"]

    def with_metrics(new_metrics, **overrides):
        forged = {
            **payload,
            "metrics": new_metrics,
            "metric_count": overrides.pop(
                "metric_count", len(new_metrics)
            ),
            **overrides,
        }
        return CanonicalAnalyticsSnapshot.from_dict(forged)

    # duplicate metric_id
    with pytest.raises(ValueError, match="ANALYTICS_METRIC_DUPLICATE"):
        with_metrics(metrics + [dict(metrics[0])])
    # missing required metric_id
    with pytest.raises(ValueError, match="ANALYTICS_METRIC_MISSING"):
        with_metrics(metrics[:-1])
    # unknown metric_id
    rogue = dict(metrics[0], metric_id="revenue_multiple_rogue")
    with pytest.raises(ValueError, match="ANALYTICS_METRIC_UNKNOWN"):
        with_metrics(metrics + [rogue])
    # metric_count mismatch
    with pytest.raises(ValueError, match="ANALYTICS_METRIC_COUNT_MISMATCH"):
        with_metrics(metrics, metric_count=len(metrics) + 1)
    # wrong canonical category / unit for a known metric
    wrong_category = [dict(m) for m in metrics]
    next(
        m for m in wrong_category if m["metric_id"] == "project_xirr"
    )["category"] = "OPERATING"
    with pytest.raises(ValueError, match="ANALYTICS_METRIC_MANIFEST_MISMATCH"):
        with_metrics(wrong_category)
    wrong_unit = [dict(m) for m in metrics]
    next(
        m for m in wrong_unit if m["metric_id"] == "senior_debt_keur"
    )["unit"] = "EUR"
    with pytest.raises(ValueError, match="ANALYTICS_METRIC_MANIFEST_MISMATCH"):
        with_metrics(wrong_unit)
    # bool is not a numeric metric value
    bool_value = [dict(m) for m in metrics]
    next(
        m for m in bool_value if m["metric_id"] == "senior_debt_keur"
    )["value"] = True
    with pytest.raises(ValueError, match="ANALYTICS_VALUE_TYPE_INVALID"):
        with_metrics(bool_value)
    # NaN / +Inf / -Inf stay rejected
    for bad in (float("nan"), float("inf"), float("-inf")):
        bad_value = [dict(m) for m in metrics]
        next(
            m for m in bad_value if m["metric_id"] == "senior_debt_keur"
        )["value"] = bad
        with pytest.raises(ValueError, match="ANALYTICS_VALUE_NOT_FINITE"):
            with_metrics(bad_value)
    # the untouched canonical payload still deserializes byte-stably
    assert CanonicalAnalyticsSnapshot.from_dict(payload).to_json() == (
        snapshot.to_json()
    )


# ---------------------------------------------------------------------------
# CORRECTION B: version proof for auto-built traces + strict value types
# ---------------------------------------------------------------------------


def test_b1_auto_built_trace_version_proof(solar):
    """CORRECTION B1: the version invariant also binds auto-built traces.

    A syntactically complete RunIdentity that lies about engine/workbook
    versions must fail closed even when no trace is supplied (the
    auto-built canonical trace carries the true repository versions).
    """
    _, run, _snapshot = solar
    rogue_engine = RunIdentity(
        snapshot_id="B1-E", composite_hash="h1",
        workbook_version="2.3.0", engine_version="engine-rogue-v9",
    )
    with pytest.raises(ValueError, match="ANALYTICS_TRACE_VERSION_MISMATCH"):
        build_canonical_analytics(run, run_identity=rogue_engine)
    rogue_workbook = RunIdentity(
        snapshot_id="B1-W", composite_hash="h2",
        workbook_version="9.9.9-rogue", engine_version="clean_senior_debt_v0",
    )
    with pytest.raises(ValueError, match="ANALYTICS_TRACE_VERSION_MISMATCH"):
        build_canonical_analytics(run, run_identity=rogue_workbook)
    # truthful identity + auto-built trace succeeds
    honest = RunIdentity(
        snapshot_id="B1-OK", composite_hash="h3",
        workbook_version="2.3.0", engine_version="clean_senior_debt_v0",
    )
    snapshot = build_canonical_analytics(run, run_identity=honest)
    assert snapshot.engine_version == "clean_senior_debt_v0"
    assert snapshot.workbook_version == "2.3.0"


def test_b2_metric_values_strict_numeric_or_null(solar):
    """CORRECTION B2: AVAILABLE values are strict numbers or null."""
    _, _, snapshot = solar
    payload = snapshot.to_dict()

    def with_value(metric_id, value):
        forged = [dict(m) for m in payload["metrics"]]
        target = next(m for m in forged if m["metric_id"] == metric_id)
        target["value"] = value
        return CanonicalAnalyticsSnapshot.from_dict(
            {**payload, "metrics": forged}
        )

    senior = "senior_debt_keur"
    for bad in ("12.3", [], {}, {"v": 1}):
        with pytest.raises(ValueError, match="ANALYTICS_VALUE_TYPE_INVALID"):
            with_value(senior, bad)
    # strict numbers succeed, including a legitimate economic 0.0
    assert with_value(senior, 27000).metric(senior).value == 27000
    assert with_value(senior, 26983.33).metric(senior).value == 26983.33
    zero = with_value(senior, 0.0)
    assert zero.metric(senior).value == 0.0
    assert zero.metric(senior).status is CanonicalMetricStatus.AVAILABLE
