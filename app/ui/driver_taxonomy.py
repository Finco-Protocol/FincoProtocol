"""Phase PR3 — Canonical Driver Taxonomy (single source of truth).

Phase PR3 establishes ONE canonical source of
truth for driver classification and sizing
terminology. Pre-PR3, the same vocabulary was
spread across:

  - ``app/ui/generic_driver_response_audit.py``
    (P1-A audit module, used WIRED_PARTIAL
    instead of DSCR_SCULPT_DRIVER)
  - ``app/ui/generic_driver_status_badges.py``
    (P1-B UI helper, used the full S2/S3
    vocabulary)
  - ``tests/test_phase_s1_*.py`` /
    ``tests/test_phase_s2_*.py`` /
    ``tests/test_phase_s3_*.py`` (per-phase
    binding / classification tests)

This module centralises:

  1. **CANONICAL_CATEGORIES** — the 6
     categories used across the codebase:

       - WIRED (fully model-affecting;
         moves revenue/EBITDA and/or IRR)
       - DSCR_SCULPT_DRIVER (binds senior
         debt / DSCR; IRR may not change)
       - TIMING_DRIVER (model-affecting via
         the construction-period timeline;
         moves equity_irr only, does NOT
         change revenue, EBITDA, senior debt,
         or DSCR)
       - REPORTING_DERIVED (user-supplied
         indicative assumption; the
         realised value is a derived output)
       - METADATA_ONLY (saved/displayed for
         context, not used by the runtime)
       - NOT_WIRED (no runtime binding; not
         on the active editable form)

  2. **CANONICAL_FIELD_MAPPING** — the 11
     editable Generic form fields and their
     canonical category.

  3. **Sizing terminology** — the
     ``EXCEL_METHODOLOGY`` constant
     (DSCR sculpt under the Generic Wind Reference/Generic Solar Reference
     external spreadsheets) is distinguished from
     the ``APP_PARITY_STRATEGY`` constant
     (Generic Wind Reference/Generic Solar Reference app paths are frozen
     reference anchors / parity by construction;
     Generic Solar/Wind use the live DSCR
     sculpt path).

  4. **Explicitly NOT on this roadmap** —
     ``manual_gearing``, ``gearing cap``,
     and ``min(gearing cap, sculpt)`` are
     explicitly listed as NOT-ON-ROADMAP
     helpers so future agents do not
     re-introduce them.

This module is the single source of truth
that future tests, helpers, and UI surfaces
should reference. Existing per-phase modules
(P1-A, P1-B, S1, S2, S3) retain their own
vocabulary for backward compatibility, but
the canonical categories in this module
MUST stay aligned with the S3 binding
suite and the P1-B UI badges.
"""

from __future__ import annotations

from typing import Tuple


# ---------------------------------------------------------------------------
# Canonical categories
# ---------------------------------------------------------------------------


CATEGORY_WIRED = "WIRED"
CATEGORY_DSCR_SCULPT_DRIVER = "DSCR_SCULPT_DRIVER"
CATEGORY_TIMING_DRIVER = "TIMING_DRIVER"
CATEGORY_REPORTING_DERIVED = "REPORTING_DERIVED"
CATEGORY_METADATA_ONLY = "METADATA_ONLY"
CATEGORY_NOT_WIRED = "NOT_WIRED"

# The 6 canonical categories. Tests
# (test_phase_pr3_taxonomy.py
# ::TestCanonicalTaxonomy) pin this tuple
# to prevent drift.
CANONICAL_CATEGORIES: Tuple[str, ...] = (
    CATEGORY_WIRED,
    CATEGORY_DSCR_SCULPT_DRIVER,
    CATEGORY_TIMING_DRIVER,
    CATEGORY_REPORTING_DERIVED,
    CATEGORY_METADATA_ONLY,
    CATEGORY_NOT_WIRED,
)


# ---------------------------------------------------------------------------
# Canonical field mapping
# ---------------------------------------------------------------------------


# 11 editable Generic form fields
# (per the Phase P1-A brief). Each field
# is mapped to its canonical category.

# WIRED — fully model-affecting, moves
# revenue/EBITDA and/or IRR.
WIRED_FIELDS: Tuple[str, ...] = (
    "tariff_eur_mwh",
    "p50_hours",
    "capacity_mw",
    "total_capex_keur",
    "opex_y1_keur",
    "ppa_term_years",
)

# DSCR_SCULPT_DRIVER — binds senior
# debt / DSCR under DSCR sculpt sizing.
# IRR may not change.
DSCR_SCULPT_DRIVER_FIELDS: Tuple[str, ...] = (
    "interest_rate_pct",
    "tenor_years",
    "target_dscr",
)

# TIMING_DRIVER — model-affecting via
# the construction-period timeline. Moves
# equity_irr only (via financial_close
# timing); does NOT change revenue,
# EBITDA, senior debt, or DSCR.
TIMING_DRIVER_FIELDS: Tuple[str, ...] = (
    "construction_months",
)

# REPORTING_DERIVED — user-supplied
# indicative assumption; the realised value
# is a derived output (e.g. realised gearing
# is computed as senior_debt / total_capex
# at runtime, not used to size debt).
REPORTING_DERIVED_FIELDS: Tuple[str, ...] = (
    "gearing_pct",
)

# METADATA_ONLY — saved/displayed for
# context, not used by the Generic runtime
# (Phase S3 emptied this set; the S3
# binding suite moved ppa_term_years to
# WIRED and construction_months to
# TIMING_DRIVER).
METADATA_ONLY_FIELDS: Tuple[str, ...] = ()

# NOT_WIRED — no runtime binding. Not on
# the active editable form. Reserved for
# future fields.
NOT_WIRED_FIELDS: Tuple[str, ...] = ()


# The full canonical field mapping, as a
# flat tuple of (field, category) pairs.
# The order matches the Phase P1-A brief
# (11 editable fields). Tests pin this
# mapping to prevent drift.
CANONICAL_FIELD_MAPPING: Tuple[Tuple[str, str], ...] = (
    ("tariff_eur_mwh", CATEGORY_WIRED),
    ("p50_hours", CATEGORY_WIRED),
    ("capacity_mw", CATEGORY_WIRED),
    ("total_capex_keur", CATEGORY_WIRED),
    ("opex_y1_keur", CATEGORY_WIRED),
    ("ppa_term_years", CATEGORY_WIRED),
    ("interest_rate_pct", CATEGORY_DSCR_SCULPT_DRIVER),
    ("tenor_years", CATEGORY_DSCR_SCULPT_DRIVER),
    ("target_dscr", CATEGORY_DSCR_SCULPT_DRIVER),
    ("construction_months", CATEGORY_TIMING_DRIVER),
    ("gearing_pct", CATEGORY_REPORTING_DERIVED),
)


# ---------------------------------------------------------------------------
# Sizing terminology
# ---------------------------------------------------------------------------


# reference methodology: Generic Wind Reference/Generic Solar Reference Excel
# workbooks use DSCR sculpt sizing. The
# app reproduces the same DSCR sculpt
# methodology on the live runtime path
# (Generic Solar / Wind) and on the
# frozen app paths (Generic Wind Reference / Generic Solar Reference).
EXCEL_METHODOLOGY: str = (
    "DSCR sculpt sizing is the canonical "
    "methodology under the Generic Wind Reference / Generic Solar Reference "
    "external spreadsheets. The app reproduces "
    "this methodology on the live runtime "
    "path (Generic Solar / Wind) and on "
    "the frozen app paths (Generic Wind Reference / Generic Solar Reference)."
)

# App validation strategy: the Generic Wind Reference and
# Generic Solar Reference app paths use explicit protected reference assumptions
# ANCHORS / PARITY BY CONSTRUCTION. The
# Generic Solar / Wind app paths are the
# LIVE DSCR SCULPT path. This is the
# honest distinction from the misleading
# shorthand "Generic Wind Reference and Generic Solar Reference app sizing
# is pure live sculpt" (which conflates
# reference methodology with app validation
# strategy).
APP_PARITY_STRATEGY: str = (
    "Generic Wind Reference / Generic Solar Reference app paths are frozen "
    "reference anchors (parity by construction). "
    "Generic Solar / Wind use the live "
    "DSCR sculpt path. The two are "
    "distinguished to avoid misleading "
    "shorthand that conflates Excel "
    "methodology with app validation strategy."
)

# Explicitly NOT on this roadmap. The
# following concepts are explicitly out of
# scope for the post-M1 trust-polish arc
# and the immediate follow-ups. Future
# agents MUST NOT re-introduce them
# without an explicit go-ahead from the
# user, and MUST NOT advertise them as
# "near-term" or "next-up" in active docs.
NOT_ON_ROADMAP_HELPERS: Tuple[str, ...] = (
    "manual_gearing",
    "gearing_cap",
    "min(gearing_cap, sculpt)",
)


NOT_ON_ROADMAP_TEXT: str = (
    "The following sizing concepts are "
    "explicitly NOT on this roadmap: "
    "manual_gearing (no manual gearing "
    "sizing method), gearing_cap (no "
    "gearing cap on the senior debt size), "
    "and min(gearing_cap, sculpt) (no "
    "blend of the gearing cap and the DSCR "
    "sculpt). They are deferred pending "
    "pilot feedback and MUST NOT be "
    "re-introduced without explicit user "
    "go-ahead. Active docs MUST NOT "
    "advertise them as 'near-term' or "
    "'next-up'."
)


# ---------------------------------------------------------------------------
# Future-agent warning copy (used by the
# canonical taxonomy note).
# ---------------------------------------------------------------------------


FUTURE_AGENT_WARNING: str = (
    "When classifying a new editable "
    "Generic form field, follow these "
    "rules to avoid brief-vs-code drift:\n"
    "  1. If the field moves revenue, "
    "EBITDA, or IRR when changed, it is "
    "WIRED.\n"
    "  2. If the field only binds senior "
    "debt / DSCR under DSCR sculpt sizing "
    "(with IRR potentially unchanged), it "
    "is DSCR_SCULPT_DRIVER.\n"
    "  3. If the field only moves the "
    "construction-period timeline and "
    "therefore equity_irr by a small "
    "amount, it is TIMING_DRIVER (not "
    "DSCR_SCULPT_DRIVER).\n"
    "  4. If the field is a user-supplied "
    "indicative assumption and the "
    "realised value is a derived output, "
    "it is REPORTING_DERIVED.\n"
    "  5. If the field is saved/displayed "
    "for context only and does not affect "
    "any runtime output, it is "
    "METADATA_ONLY.\n"
    "  6. If the field has no runtime "
    "binding at all, it is NOT_WIRED.\n"
    "Update ``CANONICAL_FIELD_MAPPING`` "
    "in this module first, then update "
    "the P1-A audit module, the P1-B UI "
    "badges helper, and the S3 binding "
    "suite to keep them in sync. Update "
    "the S3 binding suite test and the "
    "P1-B badges test to pin the new "
    "mapping. Do NOT introduce a new "
    "category without updating this "
    "module's ``CANONICAL_CATEGORIES`` "
    "tuple."
)


__all__ = [
    "CATEGORY_WIRED",
    "CATEGORY_DSCR_SCULPT_DRIVER",
    "CATEGORY_TIMING_DRIVER",
    "CATEGORY_REPORTING_DERIVED",
    "CATEGORY_METADATA_ONLY",
    "CATEGORY_NOT_WIRED",
    "CANONICAL_CATEGORIES",
    "WIRED_FIELDS",
    "DSCR_SCULPT_DRIVER_FIELDS",
    "TIMING_DRIVER_FIELDS",
    "REPORTING_DERIVED_FIELDS",
    "METADATA_ONLY_FIELDS",
    "NOT_WIRED_FIELDS",
    "CANONICAL_FIELD_MAPPING",
    "EXCEL_METHODOLOGY",
    "APP_PARITY_STRATEGY",
    "NOT_ON_ROADMAP_HELPERS",
    "NOT_ON_ROADMAP_TEXT",
    "FUTURE_AGENT_WARNING",
]
