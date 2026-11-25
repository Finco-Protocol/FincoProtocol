"""FINCO 36 Correction E — dated-grid Runs are served by canonical Python with an observable typed reason; legacy Runs keep native config."""
from __future__ import annotations

from datetime import date

import pytest

from app import project_factories as pf
from app.services.production_financial_authority import run_clean_production
from financial_engine.native_v10.config import NativeConfig, native_run, current_config
from financial_engine.native_v11.config import Stage3Config, stage3_run, current_config as v11_current_config
from financial_engine.run_scope import engine_run_scope
from tests.test_fable_batch3_date_authority_generation import _project, _with_r04


def _unproven_dated_annual(base):
    """A dated run on an unproven frequency (ANNUAL) that must remain declined run-locally."""
    from dataclasses import replace
    from finco_core.engine.period_engine import PeriodFrequency
    dated = _with_r04(base, "solar")
    return replace(dated, info=replace(dated.info, period_frequency=PeriodFrequency.ANNUAL))


def test_dated_run_admits_proved_solar_and_declines_unproven_dated_scope():
    dated_pi = _with_r04(pf.create_generic_solar_reference(), "solar")
    with native_run(NativeConfig(mode="candidate")) as v10, stage3_run(Stage3Config(mode="candidate")) as v11:
        # FINCO43B: admission is decided by the typed server-owned project type every Run route passes
        run_clean_production(dated_pi, project_type="Solar")
        assert "DATE_AUTHORITY_NATIVE_UNSUPPORTED" not in v10.declines
        assert "DATE_AUTHORITY_NATIVE_UNSUPPORTED" not in v11.declines
    # Unproven dated scope (e.g. non-semestrial frequency) still records typed run-local decline
    from app.services.production_financial_authority import _decline_native_on_dated_grid
    unproven_pi = _unproven_dated_annual(pf.create_generic_solar_reference())
    with native_run(NativeConfig(mode="candidate")) as v10, stage3_run(Stage3Config(mode="candidate")) as v11:
        with engine_run_scope():
            _decline_native_on_dated_grid(unproven_pi, "Solar")   # typed Solar: declined by the ANNUAL frequency alone
            assert current_config().mode == "off" and v11_current_config().mode == "off"
        assert v10.declines["DATE_AUTHORITY_NATIVE_UNSUPPORTED"] == 1
        assert v11.declines["DATE_AUTHORITY_NATIVE_UNSUPPORTED"] == 1
        assert current_config().mode == "candidate" and v11_current_config().mode == "candidate"
    with native_run(NativeConfig(mode="candidate")) as v10:
        run_clean_production(pf.create_generic_solar_reference())            # legacy project: no dated decline recorded
        assert "DATE_AUTHORITY_NATIVE_UNSUPPORTED" not in v10.declines


def test_scope_flag_is_run_local_no_leaked_process_state():
    from financial_engine.native_v10.config import DATE_AUTHORITY_SCOPE_KEY
    with native_run(NativeConfig(mode="candidate")):
        with engine_run_scope():
            from financial_engine.run_scope import current_run_scope
            current_run_scope()[DATE_AUTHORITY_SCOPE_KEY] = True
            assert current_config().mode == "off" and v11_current_config().mode == "off"
        assert current_config().mode == "candidate"                           # a later/other Run is unaffected


# ── actual native activation on LEGACY & proved DATED Runs; Python/native equality; concurrency; cleanup ─────────
# Uses the repository's own ``native_artifacts`` fixture: it builds the approved kernels offline, requires the committed manifest identity
# (byte-identical artifact) and installs them for the session.  Same catalogue/policy/cache handling as tests/test_native_v10_identity.py.
from tests.native_v10_support import entries, evidence_of, reset_native_caches  # noqa: E402

pytestmark = pytest.mark.usefixtures("native_artifacts")


def _run(inputs, vertical, policy, config):
    from app.services import production_financial_authority as pfa
    pfa._POLICY_RUN_CACHE.clear()
    with native_run(config) as stats:
        result = pfa.run_clean_production(inputs, project_type=vertical, financing_policy=policy)
    pfa._POLICY_RUN_CACHE.clear()
    return result, stats


def _case(name="reference-solar"):
    from tests.native_v10_support import acceptance
    factory, vertical, base = entries()[name]
    return factory(), vertical, acceptance().policy_for("canonical", base)


def test_legacy_and_proved_dated_runs_use_native_kernel_and_equal_forced_python():
    legacy, vertical, policy = _case()
    py, py_stats = _run(legacy, vertical, policy, NativeConfig(mode="off"))
    nat, stats = _run(legacy, vertical, policy, NativeConfig(mode="candidate"))
    assert py_stats.native_solves == 0
    assert stats.native_solves > 0 and stats.native_tax_evaluations > 0, stats.as_dict()   # real native dispatch, not a Python replay
    assert "DATE_AUTHORITY_NATIVE_UNSUPPORTED" not in stats.declines
    assert evidence_of(nat) == evidence_of(py)                                             # identical on the eligible legacy case
    dated = _with_r04(legacy, "solar")
    dated_py, dpy_stats = _run(dated, vertical, policy, NativeConfig(mode="off"))
    dated_nat, dstats = _run(dated, vertical, policy, NativeConfig(mode="candidate"))
    assert dpy_stats.native_solves == 0
    assert dstats.native_solves > 0 and dstats.native_tax_evaluations > 0, dstats.as_dict()
    assert "DATE_AUTHORITY_NATIVE_UNSUPPORTED" not in dstats.declines
    assert evidence_of(dated_nat) == evidence_of(dated_py)                                 # bit-identical on proved dated Solar
    assert len(dated_nat.financial_statements_result.income_statement_periods) == len(nat.financial_statements_result.income_statement_periods) + 1


def test_concurrent_legacy_and_dated_runs_do_not_leak_native_scope():
    import threading
    legacy, vertical, policy = _case()
    dated = _with_r04(legacy, "solar")
    results, errors = {}, []
    barrier = threading.Barrier(4)

    def work(key, inputs):
        try:
            barrier.wait(timeout=60)
            from app.services import production_financial_authority as pfa
            with native_run(NativeConfig(mode="candidate")) as stats:
                pfa.run_clean_production(inputs, project_type=vertical, financing_policy=policy)
                results[key] = stats.as_dict()
        except Exception as exc:  # noqa: BLE001
            errors.append((key, repr(exc)))

    threads = [threading.Thread(target=work, args=(f"{kind}{i}", inp)) for i in range(2) for kind, inp in (("legacy", legacy), ("dated", dated))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    for key, stats in results.items():
        assert "DATE_AUTHORITY_NATIVE_UNSUPPORTED" not in stats["declines"], (key, stats)
    assert any(k.startswith("legacy") and v["native_solves"] > 0 for k, v in results.items()), results
    assert any(k.startswith("dated") and v["native_solves"] > 0 for k, v in results.items()), results


def test_failed_dated_run_leaves_no_scope_state_for_the_next_legacy_run():
    from dataclasses import replace
    from app.services import production_financial_authority as pfa
    legacy, vertical, policy = _case()
    dated = _with_r04(legacy, "solar")
    broken = replace(dated, financing=replace(dated.financing, gearing_ratio=0.0))      # unsupported zero gearing -> the Run raises
    pfa._POLICY_RUN_CACHE.clear()
    with native_run(NativeConfig(mode="candidate")) as stats:
        with pytest.raises(Exception):
            pfa.run_clean_production(broken, project_type=vertical, financing_policy=policy)
        assert current_config().mode == "candidate"                                        # the flag died with the failed Run's scope
        pfa._POLICY_RUN_CACHE.clear()
        pfa.run_clean_production(legacy, project_type=vertical, financing_policy=policy)
        assert stats.native_solves > 0
    pfa._POLICY_RUN_CACHE.clear()
