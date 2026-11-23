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


def test_dated_run_declines_native_with_typed_reason_and_legacy_run_does_not():
    dated_pi = _with_r04(pf.create_generic_solar_reference(), "solar")
    with native_run(NativeConfig(mode="candidate")) as v10, stage3_run(Stage3Config(mode="candidate")) as v11:
        run_clean_production(dated_pi)
        assert v10.declines["DATE_AUTHORITY_NATIVE_UNSUPPORTED"] == 1
        assert v11.declines["DATE_AUTHORITY_NATIVE_UNSUPPORTED"] == 1
        assert v10.native_solves == v10.native_finalisations == v10.native_tax_evaluations == 0
        assert v11.native_models == 0
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
