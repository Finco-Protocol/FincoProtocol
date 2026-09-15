"""Revenue input contract validation — shared by adapter, update-service, and run preflight.

Rules:
- FIRST_FULL_CALENDAR_YEAR_AS_BASE: date optional (ignored).
- AFTER_FIRST_FULL_OPERATING_YEAR: date optional (ignored; escalation anchored to COD).
- CONTRACT_ANNIVERSARY: ppa_indexation_start_date required.

Raises RevenueInputError (a ValueError subclass) with a human-readable message.
"""
from __future__ import annotations


class RevenueInputError(ValueError):
    """Controlled revenue input contract violation — safe to surface to users."""


def validate_revenue_ppa_cross_field(
    *,
    ppa_indexation_start_policy: str | None,
    ppa_indexation_start_date=None,
) -> None:
    """Validate the cross-field contract between policy and date.

    Raises RevenueInputError when CONTRACT_ANNIVERSARY is selected but no
    indexation start date has been provided.
    """
    if ppa_indexation_start_policy == "CONTRACT_ANNIVERSARY":
        if not ppa_indexation_start_date:
            raise RevenueInputError(
                "Escalation Base Year Policy is CONTRACT_ANNIVERSARY but no "
                "Indexation Start Date has been set. "
                "Please enter the PPA / indexation reference start date "
                "(the date from which annual anniversaries are counted)."
            )
