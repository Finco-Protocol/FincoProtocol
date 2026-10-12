"""Candidate F3.5-A bridge using the existing financing CAS field, no sidecar."""
from dataclasses import replace

from finco_core.inputs.financing_instruments import FinancingCollection, FinancingError
from finco_core.inputs.junior_debt import AUTHORITY, JuniorDebtPolicy, activate_collection, validate_collection

# Candidate content is executable locally, but is not released financial authority.
ACTIVATION_ENABLED = False
ACTIVATION_KEYS = {"authority", "proposal_digest", "sponsor_funding_mode", "reserve_support_mode", "junior_policy"}


def validate_activation(collection, activation):
    if not isinstance(activation, dict) or set(activation) != ACTIVATION_KEYS:
        raise FinancingError("F35_WORKSPACE_ACTIVATION_INVALID")
    if (activation["authority"] != AUTHORITY or activation["proposal_digest"] != collection.content_digest()
            or activation["sponsor_funding_mode"] != "EQUITY_ONLY" or activation["reserve_support_mode"] != "NONE"):
        raise FinancingError("F35_WORKSPACE_ACTIVATION_BINDING_INVALID")
    policy = JuniorDebtPolicy.from_dict(activation["junior_policy"])
    validate_collection(collection, policy)
    return policy


def apply_entry(pi, entry, *, enforce_release):
    if enforce_release and not ACTIVATION_ENABLED:
        raise FinancingError("F35_CANDIDATE_CONTENT_REVIEW_REQUIRED")
    from app.workbook.multisenior_config import activation_financing_params
    from financial_engine.financing.junior_debt import validate_project_boundary
    collection = FinancingCollection.from_dict(entry["proposal"])
    policy = validate_activation(collection, entry["activation"])
    active = activate_collection(replace(pi, financing=activation_financing_params(pi.financing)), collection, policy)
    validate_project_boundary(active)
    return active
