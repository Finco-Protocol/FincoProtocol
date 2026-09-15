"""Phase P1-B + Phase S2 + Phase S3 — Generic Driver Status Badges / Metadata helpers.

Pure read-side helper module. Provides the driver
status vocabulary, badge class names, tooltip
copy, and the field-to-status mapping for the
Generic Solar / Wind input form.

This is the UI explanation layer that follows the
Phase P1-A driver-response audit, the Phase S2
gearing-as-output rule, and the Phase S3
driver-to-KPI binding suite. The helper does NOT
mutate any input, does NOT call the runtime, does
NOT change formulas.

Mapping (per PR #600 audit, branch f8ae191; refined
by Phase S2; refined again by Phase S3 binding
suite; refined once more by the S3 review fix
that split the sculpt-driver and timing-driver
concepts):

  WIRED (6 fields, no badge by default):
    - tariff_eur_mwh
    - p50_hours
    - capacity_mw
    - total_capex_keur
    - opex_y1_keur
    - ppa_term_years

  DSCR SCULPT DRIVER (3 fields, "DSCR sculpt driver"
    badge):
    - interest_rate_pct
    - tenor_years
    - target_dscr

  TIMING DRIVER (1 field, "Timing driver" badge, NEW
    in S3 review fix): this is a separate concept
    from the DSCR sculpt drivers. A timing driver
    is a model-affecting field that influences the
    construction-period timeline (and therefore
    equity_irr via financial_close timing), but
    does NOT change revenue, EBITDA, senior debt,
    or DSCR.
    - construction_months (moves equity_irr via
      the financial_close timeline by ~10bps
      spread between 6mo and 36mo construction
      periods, but does not move revenue, EBITDA,
      senior debt, or DSCR. Pre-S1 was
      METADATA_ONLY; the S1 schema extension
      accepts it; the resolver applies it via
      info override / financial_close timing.)

  REPORTING_DERIVED (1 field, Phase S2):
    - gearing_pct

  METADATA_ONLY: 0 fields (Phase S3 emptied this
    set)
  NOT_WIRED: 0 fields

Phase S2 amendment: gearing_pct is no longer labeled
as a DSCR sculpt driver. Under DSCR sculpt, the
sizing CFADS basis sizes senior debt to hit
target_dscr. gearing_pct is the user-supplied
indicative gearing assumption; the realized
gearing_ratio is a DERIVED OUTPUT computed as
senior_debt_keur / total_capex_keur. The user-facing
label is now "Indicative (derived)" with copy that
explains the relationship.

Phase S3 amendment: ppa_term_years moved out of
METADATA_ONLY. The S1 resolver added
_set_revenue_ppa_term, which applies
ppa_term_years to the revenue duration. Changing
ppa_term_years moves total_revenue_keur and
total_ebitda_keur. ppa_term_years is now WIRED.

Phase S3 review fix: construction_months is split
out of DSCR_SCULPT_DRIVER_FIELDS into a new
TIMING_DRIVER_FIELDS set. The previous S3 mapping
incorrectly grouped construction_months with the
3 binding sculpt drivers. The correct semantic is
that construction_months affects the
construction-period timing (and therefore
equity_irr by a small amount), but does not bind
senior debt, DSCR, revenue, or EBITDA. The 3 true
DSCR sculpt drivers (interest_rate_pct,
tenor_years, target_dscr) are kept in
DSCR_SCULPT_DRIVER_FIELDS with the "DSCR sculpt
driver" badge. construction_months gets a new
"Timing driver" badge with a separate CSS class
(badge-timing, soft amber palette) to make the
distinction visually clear.

CSS class reuse note: TIMING_DRIVER reuses the
existing badge-metadata and badge-dscr-sculpt CSS
classes internally for layout (border, padding,
font-size) but uses a new badge-timing class for
the color palette (soft amber) and a new
TOOLTIP_TIMING_DRIVER copy that explicitly
distinguishes it from the DSCR sculpt drivers.
The user-facing badge text is "Timing driver"
(never "DSCR sculpt driver").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Status vocabulary
# ---------------------------------------------------------------------------


STATUS_WIRED = "WIRED"
STATUS_WIRED_PARTIAL = "WIRED_PARTIAL"
STATUS_METADATA_ONLY = "METADATA_ONLY"
STATUS_NOT_WIRED = "NOT_WIRED"
# Phase S2: gearing_pct is now REPORTING_DERIVED
# (the realized gearing is a derived output, the
# input value is an indicative assumption).
STATUS_REPORTING_DERIVED = "REPORTING_DERIVED"
# Phase S3 review fix: construction_months is now
# STATUS_TIMING_DRIVER (a separate concept from
# STATUS_WIRED_PARTIAL). Timing drivers are
# model-affecting fields that influence the
# construction-period timeline (and therefore
# equity_irr via financial_close timing), but do
# NOT change revenue, EBITDA, senior debt, or
# DSCR. This is a tighter classification than
# the previous S3 round-1 placement in
# DSCR_SCULPT_DRIVER_FIELDS.
STATUS_TIMING_DRIVER = "TIMING_DRIVER"

ALL_STATUSES: tuple[str, ...] = (
    STATUS_WIRED,
    STATUS_WIRED_PARTIAL,
    STATUS_METADATA_ONLY,
    STATUS_NOT_WIRED,
    STATUS_REPORTING_DERIVED,
    STATUS_TIMING_DRIVER,
)

# P1-B badge vocabulary (the labels we render in the UI).
BADGE_METADATA_ONLY = "Metadata only"
BADGE_DSCR_SCULPT_DRIVER = "DSCR sculpt driver"
# Phase S2: badge for gearing_pct. "Indicative (derived)"
# tells the pilot user that the input value is an
# indicative assumption and the realized gearing is
# computed as a derived output.
BADGE_REPORTING_DERIVED = "Indicative (derived)"
# Phase S3 review fix: badge for construction_months.
# "Timing driver" tells the pilot user that this
# field is model-affecting via the construction-
# period timeline (and therefore equity_irr via
# financial_close timing) but does NOT change
# revenue, EBITDA, senior debt, or DSCR. This is
# honest copy: the previous "DSCR sculpt driver"
# label implied construction_months binds senior
# debt / DSCR, which it does not.
BADGE_TIMING_DRIVER = "Timing driver"
# Fully wired fields get no badge by default
# (the form stays uncluttered per the P1-B brief).
BADGE_NONE: Optional[str] = None

# CSS class names that the inputs_section.html
# uses to render the badge.
CSS_CLASS_METADATA = "badge-metadata"
CSS_CLASS_DSCR_SCULPT = "badge-dscr-sculpt"
# Phase S2: new CSS class for derived/reporting
# fields. Visually distinct from metadata-only
# (which is a "no effect" badge) and from
# DSCR sculpt (which is a "binds" badge).
CSS_CLASS_REPORTING = "badge-reporting"
# Phase S3 review fix: new CSS class for timing
# drivers. Visually distinct from metadata-only
# (gray), DSCR sculpt (blue), and reporting
# (green). Soft amber palette signals "model-
# affecting via the timeline, not the engine".
# Internal layout (border, padding, font-size) is
# shared with the other badge classes for visual
# consistency.
CSS_CLASS_TIMING = "badge-timing"
CSS_CLASS_NONE: Optional[str] = None


# ---------------------------------------------------------------------------
# Tooltip copy (per the P1-B brief)
# ---------------------------------------------------------------------------


TOOLTIP_METADATA_ONLY: str = (
    "This field is saved/displayed for context but "
    "is not currently used by the Generic runtime "
    "calculation."
)

TOOLTIP_DSCR_SCULPT_DRIVER: str = (
    "This field affects debt / equity / DSCR outputs "
    "under the current DSCR sculpting method. "
    "Project IRR may not change."
)

# Phase S3 review fix: tooltip for construction_months.
# Honest copy: timing drivers are model-affecting
# fields that influence the construction-period
# timeline (and therefore equity_irr via financial_close
# timing), but do NOT change revenue, EBITDA,
# senior debt, or DSCR. This is the explicit
# distinction from the DSCR sculpt drivers above
# (which DO bind senior debt / DSCR).
TOOLTIP_TIMING_DRIVER: str = (
    "This field is a timing driver. It affects the "
    "construction-period timeline and can move "
    "equity IRR via the financial_close timing, "
    "but it does NOT change revenue, EBITDA, "
    "senior debt, or DSCR in the current Generic "
    "runtime."
)

# Phase S2: tooltip for the gearing_pct field.
# Honest copy: gearing is a user-supplied
# indicative assumption; the realized gearing is
# a derived output (computed as senior_debt /
# total_capex at runtime). Under DSCR sculpt, the
# senior debt amount is sized to hit target_dscr;
# the user-supplied gearing_pct is preserved as
# a reporting/derived metric but is NOT the
# binding driver of senior debt size.
TOOLTIP_REPORTING_DERIVED: str = (
    "Indicative gearing assumption. The realized "
    "gearing is shown as a derived output (senior "
    "debt / total CAPEX). Under DSCR sculpt sizing, "
    "senior debt is sized to hit target DSCR, so the "
    "user-supplied gearing_pct is preserved as a "
    "reporting metric, not as a binding senior debt "
    "sizing driver."
)


# ---------------------------------------------------------------------------
# Field-to-status mapping
# ---------------------------------------------------------------------------


METADATA_ONLY_FIELDS: tuple[str, ...] = (
    # Phase S3: ppa_term_years and construction_months
    # are no longer METADATA_ONLY. The S1 resolver
    # added _set_revenue_ppa_term (which applies
    # ppa_term_years) and the schema extension
    # (which accepts construction_months), so both
    # fields are now model-affecting. See
    # WIRED_FIELDS and DSCR_SCULPT_DRIVER_FIELDS.
)

# Phase S2: gearing_pct is no longer a DSCR sculpt
# driver. It is a user-supplied indicative gearing
# assumption; the realized gearing is a derived
# output (computed as senior_debt / total_capex).
# The field maps to REPORTING_DERIVED.
REPORTING_DERIVED_FIELDS: tuple[str, ...] = (
    "gearing_pct",
)

DSCR_SCULPT_DRIVER_FIELDS: tuple[str, ...] = (
    # Phase S2: gearing_pct removed (moved to
    # REPORTING_DERIVED_FIELDS).
    # Phase S3 review fix: construction_months
    # removed (moved to TIMING_DRIVER_FIELDS). It
    # is NOT a DSCR sculpt driver; it is a timing
    # driver (moves equity_irr via financial_close
    # timing, does not change revenue/EBITDA/senior
    # debt/DSCR). The 3 fields below are the
    # true DSCR sculpt drivers.
    "interest_rate_pct",
    "tenor_years",
    "target_dscr",
)

# Phase S3 review fix: construction_months is a
# timing driver, not a DSCR sculpt driver. It is
# model-affecting (the S1 schema extension accepts
# it; the resolver applies it via info override /
# financial_close timing) but it does NOT bind
# senior debt or DSCR; it only moves equity_irr
# via the construction-period timeline.
TIMING_DRIVER_FIELDS: tuple[str, ...] = (
    "construction_months",
)

WIRED_FIELDS: tuple[str, ...] = (
    # Phase S3: ppa_term_years added. The S1
    # resolver added _set_revenue_ppa_term, so
    # changing ppa_term_years moves total_revenue_keur
    # and total_ebitda_keur. Pre-S1 this was
    # classified as METADATA_ONLY because the
    # resolver had no _set_revenue_ppa_term helper.
    "tariff_eur_mwh",
    "p50_hours",
    "capacity_mw",
    "total_capex_keur",
    "opex_y1_keur",
    "ppa_term_years",
)

NOT_WIRED_FIELDS: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Field status entry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldDriverStatus:
    """A single field's UI status for the form."""

    #: The field key (e.g. "gearing_pct").
    field: str

    #: The audit status: WIRED, WIRED_PARTIAL,
    #: METADATA_ONLY, NOT_WIRED.
    status: str

    #: The badge text to render next to the field
    #: (or None for fully wired fields).
    badge_text: Optional[str]

    #: The CSS class to apply to the badge (or None).
    badge_class: Optional[str]

    #: The tooltip copy (or None for fully wired).
    badge_title: Optional[str]


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


def is_metadata_only_field(field: str) -> bool:
    """Return True if the field is in the
    METADATA_ONLY set."""
    return field in METADATA_ONLY_FIELDS


def is_reporting_derived_field(field: str) -> bool:
    """Phase S2: return True if the field is in the
    REPORTING_DERIVED set (e.g. gearing_pct)."""
    return field in REPORTING_DERIVED_FIELDS


def is_dscr_sculpt_driver_field(field: str) -> bool:
    """Return True if the field is in the DSCR
    SCULPT DRIVER set (3 fields:
    interest_rate_pct, tenor_years, target_dscr).

    Note: construction_months is NOT a DSCR sculpt
    driver; it is a TIMING driver (see
    is_timing_driver_field)."""
    return field in DSCR_SCULPT_DRIVER_FIELDS


def is_timing_driver_field(field: str) -> bool:
    """Phase S3 review fix: return True if the
    field is in the TIMING_DRIVER set (currently
    just construction_months)."""
    return field in TIMING_DRIVER_FIELDS


def is_wired_field(field: str) -> bool:
    """Return True if the field is in the WIRED set."""
    return field in WIRED_FIELDS


def get_field_status(field: str) -> str:
    """Return the audit status for a field."""
    if is_metadata_only_field(field):
        return STATUS_METADATA_ONLY
    if is_reporting_derived_field(field):
        return STATUS_REPORTING_DERIVED
    # Phase S3 review fix: TIMING_DRIVER is checked
    # before DSCR_SCULPT_DRIVER. construction_months
    # is a timing driver, not a DSCR sculpt driver.
    if is_timing_driver_field(field):
        return STATUS_TIMING_DRIVER
    if is_dscr_sculpt_driver_field(field):
        return STATUS_WIRED_PARTIAL
    if is_wired_field(field):
        return STATUS_WIRED
    return STATUS_NOT_WIRED


def get_field_badge(field: str) -> FieldDriverStatus:
    """Return the FieldDriverStatus (status, badge
    text, badge class, tooltip) for a field.

    Fully wired fields return badge_text=None so
    the template does not render a badge."""
    if is_metadata_only_field(field):
        return FieldDriverStatus(
            field=field,
            status=STATUS_METADATA_ONLY,
            badge_text=BADGE_METADATA_ONLY,
            badge_class=CSS_CLASS_METADATA,
            badge_title=TOOLTIP_METADATA_ONLY,
        )
    # Phase S2: REPORTING_DERIVED is checked before
    # DSCR_SCULPT_DRIVER. The reporting/derived
    # status takes precedence (gearing_pct is no
    # longer a binding sculpt driver).
    if is_reporting_derived_field(field):
        return FieldDriverStatus(
            field=field,
            status=STATUS_REPORTING_DERIVED,
            badge_text=BADGE_REPORTING_DERIVED,
            badge_class=CSS_CLASS_REPORTING,
            badge_title=TOOLTIP_REPORTING_DERIVED,
        )
    # Phase S3 review fix: TIMING_DRIVER is checked
    # before DSCR_SCULPT_DRIVER. construction_months
    # is a timing driver, not a DSCR sculpt driver.
    if is_timing_driver_field(field):
        return FieldDriverStatus(
            field=field,
            status=STATUS_TIMING_DRIVER,
            badge_text=BADGE_TIMING_DRIVER,
            badge_class=CSS_CLASS_TIMING,
            badge_title=TOOLTIP_TIMING_DRIVER,
        )
    if is_dscr_sculpt_driver_field(field):
        return FieldDriverStatus(
            field=field,
            status=STATUS_WIRED_PARTIAL,
            badge_text=BADGE_DSCR_SCULPT_DRIVER,
            badge_class=CSS_CLASS_DSCR_SCULPT,
            badge_title=TOOLTIP_DSCR_SCULPT_DRIVER,
        )
    if is_wired_field(field):
        return FieldDriverStatus(
            field=field,
            status=STATUS_WIRED,
            badge_text=BADGE_NONE,
            badge_class=CSS_CLASS_NONE,
            badge_title=None,
        )
    return FieldDriverStatus(
        field=field,
        status=STATUS_NOT_WIRED,
        badge_text=None,
        badge_class=None,
        badge_title=None,
    )


# ---------------------------------------------------------------------------
# Exploratory / warning copy (used by the partial)
# ---------------------------------------------------------------------------


EXPLORATORY_NOTICE_TEXT: str = (
    "This Generic project is editable for sketching "
    "scenarios, but the runtime output has not been "
    "validated against an reference evidence. Outputs are "
    "not lender-ready, audit-ready, or bank-approved. "
    "Use only for exploratory analysis."
)


__all__ = [
    "STATUS_WIRED",
    "STATUS_WIRED_PARTIAL",
    "STATUS_METADATA_ONLY",
    "STATUS_NOT_WIRED",
    "STATUS_REPORTING_DERIVED",
    # Phase S3 review fix: TIMING_DRIVER is a
    # separate concept from WIRED_PARTIAL.
    "STATUS_TIMING_DRIVER",
    "ALL_STATUSES",
    "BADGE_METADATA_ONLY",
    "BADGE_DSCR_SCULPT_DRIVER",
    "BADGE_REPORTING_DERIVED",
    # Phase S3 review fix: badge for TIMING_DRIVER
    # (currently just construction_months).
    "BADGE_TIMING_DRIVER",
    "BADGE_NONE",
    "CSS_CLASS_METADATA",
    "CSS_CLASS_DSCR_SCULPT",
    "CSS_CLASS_REPORTING",
    # Phase S3 review fix: new CSS class for
    # TIMING_DRIVER.
    "CSS_CLASS_TIMING",
    "CSS_CLASS_NONE",
    "TOOLTIP_METADATA_ONLY",
    "TOOLTIP_DSCR_SCULPT_DRIVER",
    "TOOLTIP_REPORTING_DERIVED",
    # Phase S3 review fix: tooltip for TIMING_DRIVER.
    "TOOLTIP_TIMING_DRIVER",
    "METADATA_ONLY_FIELDS",
    "REPORTING_DERIVED_FIELDS",
    "DSCR_SCULPT_DRIVER_FIELDS",
    # Phase S3 review fix: new field set.
    "TIMING_DRIVER_FIELDS",
    "WIRED_FIELDS",
    "NOT_WIRED_FIELDS",
    "FieldDriverStatus",
    "is_metadata_only_field",
    "is_reporting_derived_field",
    "is_dscr_sculpt_driver_field",
    # Phase S3 review fix: new helper.
    "is_timing_driver_field",
    "is_wired_field",
    "get_field_status",
    "get_field_badge",
    "EXPLORATORY_NOTICE_TEXT",
]
