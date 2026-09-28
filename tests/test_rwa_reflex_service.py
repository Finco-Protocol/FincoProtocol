from datetime import timedelta

from app.radar_rwa.reflex import EmpiricalTransientBaselineConfig, JevReflexConfig, ReflexExperimentService
from tests.rwa_reflex_helpers import NOW, authority, context


class Evaluator:
    def __init__(self): self.calls = 0
    def evaluate(self, request):
        self.calls += 1
        return {"model": "jev-1.13.0", "answers": {"likely_transient": {"type": "noul", "noul": 0.72}}}


def baseline_config():
    return EmpiricalTransientBaselineConfig(
        training_cutoff=NOW - timedelta(days=1), training_source="FROZEN_PREPERIOD_CANONICAL_EVENTS",
        global_transient_count=12, global_total_count=20,
        cell_counts={"OPEN|100_TO_199_BPS|25K_TO_99K_USD": (8, 10)},
    )


def test_internal_harness_default_disabled_and_baseline_explicitly_unavailable_without_history():
    payload = ReflexExperimentService().evaluate(authority(), as_of=NOW, context=context())
    assert payload["experimental"] is True
    assert payload["authority_boundary"] == "FINCO_CANONICAL_AUTHORITY_ONLY"
    assert payload["interpretation"]["state"] == "DISABLED"
    assert payload["baseline"]["state"] == "UNAVAILABLE"


def test_enabled_without_transport_fails_closed():
    payload = ReflexExperimentService(jev_config=JevReflexConfig(enabled=True), baseline_config=baseline_config()).evaluate(
        authority(), as_of=NOW, context=context())
    assert payload["interpretation"]["state"] == "UNAVAILABLE"
    assert payload["interpretation"]["reason"] == "JEV_TRANSPORT_NOT_CONFIGURED"
    assert payload["baseline"]["state"] == "AVAILABLE"


def test_jev_and_baseline_share_same_information_set_but_canonical_state_is_unchanged():
    evaluator = Evaluator()
    payload = ReflexExperimentService(
        jev_transport=evaluator, jev_config=JevReflexConfig(enabled=True), baseline_config=baseline_config(),
    ).evaluate(authority(), as_of=NOW, context=context())
    assert evaluator.calls == 1
    assert payload["reflex_state"]["reference_premium_bps"] == "142"
    assert payload["reflex_state"]["premium_deviation_bps"] == "122"
    assert payload["interpretation"]["state"] == "AVAILABLE"
    assert payload["interpretation"]["likely_transient_probability"] == "0.72"
    assert payload["interpretation"]["resolved_model"] == "jev-1.13.0"
    assert payload["baseline"]["transient_probability"] == "0.7"
    assert payload["baseline"]["information_parity"] == "RWA_REFLEX_JEV_BASELINE_INFORMATION_PARITY"
