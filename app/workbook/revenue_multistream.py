"""Workspace bridge to the explicit dated revenue authority, never a calculator."""
from dataclasses import fields, replace

from domain.revenue.multistream_runtime import parse_config

FIELD_ID = "revenue.multistream.contracts"
SNAPSHOT_KEY = "rev_multistream_config_json"


def assert_legacy_pricing_edit(snapshot, field_id):
    if snapshot.get(SNAPSHOT_KEY) and field_id.startswith(("revenue.ppa.", "revenue.merchant.")):
        raise ValueError("REVENUE_V2_PRICING_AUTHORITY: edit the explicit revenue contracts instead of legacy pricing")


def canonical_json(raw):
    config = parse_config(raw)
    return config.canonical_json if config is not None else ""


def apply_config(inputs, raw, *, project_type):
    config = parse_config(raw)
    if config is None:
        return inputs
    if str(project_type).strip().lower() != config.technology:
        raise ValueError("REVENUE_V2_TECHNOLOGY: contract technology must match the project")
    from finco_core.inputs._models import RevenueParams
    from finco_core.inputs.revenue_multistream import MultiStreamRevenueParams
    revenue = MultiStreamRevenueParams(**{f.name: getattr(inputs.revenue, f.name) for f in fields(RevenueParams)},
                                       multistream_config_json=config.canonical_json)
    candidate = replace(inputs, revenue=revenue)
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.orchestrator import _build_period_engine
    config.validate_axis(_build_period_engine(from_project_inputs(candidate)).periods())
    return candidate
