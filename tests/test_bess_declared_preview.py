"""Declared terms remain an ephemeral schema review, never financial results."""
import json
from unittest.mock import patch
import pytest
from domain.bess.synthetic import example
from app.services.bess_setup_preview import preview


@pytest.mark.parametrize("variable_om", [0, 1.25])
def test_declared_terms_preserve_zero_units_and_unknown_financial_authority(variable_om):
    config = example("2028-01-01T00:00:00Z", "2028-01-03T00:00:00Z")
    raw = json.dumps({"version": 1, "configuration": config, "variable_om_eur_per_dc_mwh": variable_om})
    with patch("app.persistence.projects_repository.save_project", side_effect=AssertionError("write")), \
         patch("app.services.production_financial_authority.run_clean_production", side_effect=AssertionError("Run")):
        result = preview(raw, {})
    terms = result["declared_terms"]
    assert terms["costs"]["variable_om"] == {"status": "DECLARED", "value": str(variable_om), "unit": "EUR/DC MWh"}
    assert terms["costs"]["capex"] == {"status": "NOT_AVAILABLE", "value": None}
    assert terms["financing"]["funding"] == {"status": "NOT_AVAILABLE", "value": None}
    assert set(terms["battery"]["values"]) == set(terms["battery"]["units"])
    assert terms["group_order"][-1] == "notes"
    assert len(terms["dispatch_and_prices"]["rows"]) <= 24
    assert "source_ref" not in str(terms)
    assert not any(terms["review"][key] for key in ("persisted", "run_supported", "save_supported", "physical_balance_verified", "financial_horizon_verified"))
    assert terms["review"]["financial_calculation_count"] == 0
