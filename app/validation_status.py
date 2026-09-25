"""G1D: user-facing validation status reporting.

Defines a structured, project-level and metric-level validation status
schema that the UI and Excel/export pipelines can both consume. This
module does not run the runtime, does not touch any waterfall/tax/debt
formula, and does not change any project factory default. It only
classifies and labels existing outputs.

Wording rules (see ``PROJECT_VALIDATION_STATUSES`` and
``DISCLOSURE_TEXT``): user-facing text avoids internal engineering terms
such as "factory", "baseline", "hardcoded", or "bootstrap". Those terms
remain fine in audit/dev docs (e.g. docs/, reports/) but must not leak
into anything rendered to an end user or written into an export.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ValidationTier(str, Enum):
    """Project-level validation tier."""

    SYNTHETIC_REFERENCE = "synthetic_reference"
    VALIDATED_WITH_CAVEATS = "validated_with_caveats"
    DESIGN_ONLY = "design_only"
    EXPERIMENTAL = "experimental"


TIER_LABELS: dict[ValidationTier, str] = {
    ValidationTier.SYNTHETIC_REFERENCE: "Synthetic reference model",
    ValidationTier.VALIDATED_WITH_CAVEATS: "Validated model with caveats",
    ValidationTier.DESIGN_ONLY: "Design-only, not externally validated",
    ValidationTier.EXPERIMENTAL: "Experimental, internal only",
}

TIER_TONE: dict[ValidationTier, str] = {
    # Matches the tone vocabulary already used by
    # app/templates/partials/_validation_summary_bar.html.
    ValidationTier.SYNTHETIC_REFERENCE: "pass",
    ValidationTier.VALIDATED_WITH_CAVEATS: "warn",
    ValidationTier.DESIGN_ONLY: "warn",
    ValidationTier.EXPERIMENTAL: "fail",
}


class MetricValidationLevel(str, Enum):
    VALIDATED = "validated"
    METHODOLOGY_CAVEAT = "methodology_caveat"


@dataclass(frozen=True)
class MetricValidationLabel:
    metric_key: str
    display_name: str
    level: MetricValidationLevel
    caveat_text: str = ""


@dataclass(frozen=True)
class ProjectValidationStatus:
    project_key: str
    display_name: str
    tier: ValidationTier
    tier_label: str
    tier_tone: str
    tier_description: str
    metrics: tuple[MetricValidationLabel, ...]
    disclosures: tuple[str, ...]
    # Audit/dev-facing classification string (e.g. for docs/, reports/,
    # internal review tooling). May use internal terms such as "factory" or
    # internal development terms -- never render this in the UI or in
    # an end-user-facing export; use ``tier_label``/``tier_description``
    # for that instead.
    internal_classification: str = ""

    def metric(self, metric_key: str) -> MetricValidationLabel | None:
        for entry in self.metrics:
            if entry.metric_key == metric_key:
                return entry
        return None

    def validated_metrics(self) -> tuple[MetricValidationLabel, ...]:
        return tuple(m for m in self.metrics if m.level == MetricValidationLevel.VALIDATED)

    def caveated_metrics(self) -> tuple[MetricValidationLabel, ...]:
        return tuple(m for m in self.metrics if m.level == MetricValidationLevel.METHODOLOGY_CAVEAT)


# ---------------------------------------------------------------------------
# Shared disclosure text (user-facing).
# ---------------------------------------------------------------------------

DISCLOSURE_GENERIC_REFERENCE_SCOPE = (
    "Generic Solar and Generic Wind are validated against internal reference "
    "workbooks, not a full external bank model review."
)
DISCLOSURE_METHODOLOGY_CAVEAT = (
    "Debt service shape, DSCR, and IRR figures carry a documented methodology "
    "caveat versus the reference methodology (see validation notes)."
)
DISCLOSURE_NOT_ADVICE = (
    "All outputs are financial modelling estimates only and do not "
    "constitute legal, tax, accounting, or investment advice."
)
DISCLOSURE_NOT_EXTERNALLY_VALIDATED = (
    "This configuration is not externally validated."
)

DISCLOSURE_TEXT: tuple[str, ...] = (
    DISCLOSURE_GENERIC_REFERENCE_SCOPE,
    DISCLOSURE_METHODOLOGY_CAVEAT,
    DISCLOSURE_NOT_ADVICE,
)

_NOT_ADVICE_ONLY: tuple[str, ...] = (DISCLOSURE_NOT_ADVICE,)
_NOT_EXTERNALLY_VALIDATED: tuple[str, ...] = (
    DISCLOSURE_NOT_EXTERNALLY_VALIDATED,
    DISCLOSURE_NOT_ADVICE,
)


# ---------------------------------------------------------------------------
# Generic Solar/Wind metric-level labels.
# ---------------------------------------------------------------------------

_GENERIC_VALIDATED_METRICS: tuple[tuple[str, str], ...] = (
    ("total_capex_keur", "CAPEX"),
    ("total_revenue_keur", "Revenue"),
    ("total_opex_keur", "OPEX"),
    ("total_ebitda_keur", "EBITDA"),
    ("idc_keur", "IDC"),
    ("bank_fees_keur", "Bank fees"),
    ("senior_debt_keur", "Senior debt amount"),
    ("realized_gearing", "Realized gearing"),
    ("equity_funding_stack_keur", "Equity funding stack"),
)

_GENERIC_CAVEAT_METRICS: tuple[tuple[str, str, str], ...] = (
    (
        "senior_debt_service_keur",
        "Debt service shape",
        "Senior debt service amortization shape differs from the reference "
        "workbook's own debt-sizing approach; see methodology notes.",
    ),
    (
        "avg_dscr",
        "Average DSCR",
        "Average DSCR is sensitive to the debt-sizing methodology gap; see "
        "methodology notes.",
    ),
    (
        "min_dscr",
        "Minimum DSCR",
        "Minimum DSCR is sensitive to the debt-sizing methodology gap; see "
        "methodology notes.",
    ),
    (
        "project_irr",
        "Project IRR",
        "Project IRR is calculated on an unlevered basis and can diverge from "
        "the selected tax methodology; "
        "see methodology notes.",
    ),
    (
        "equity_irr",
        "Equity IRR",
        "Equity IRR carries a wider tolerance pending a tighter tolerance "
        "review; see methodology notes.",
    ),
)


def _generic_metrics() -> tuple[MetricValidationLabel, ...]:
    validated = tuple(
        MetricValidationLabel(key, label, MetricValidationLevel.VALIDATED)
        for key, label in _GENERIC_VALIDATED_METRICS
    )
    caveated = tuple(
        MetricValidationLabel(key, label, MetricValidationLevel.METHODOLOGY_CAVEAT, caveat_text=text)
        for key, label, text in _GENERIC_CAVEAT_METRICS
    )
    return validated + caveated


def _reference_project_status(project_key: str, display_name: str) -> ProjectValidationStatus:
    return ProjectValidationStatus(
        project_key=project_key,
        display_name=display_name,
        tier=ValidationTier.SYNTHETIC_REFERENCE,
        tier_label=TIER_LABELS[ValidationTier.SYNTHETIC_REFERENCE],
        tier_tone=TIER_TONE[ValidationTier.SYNTHETIC_REFERENCE],
        tier_description=(
            f"{display_name} is a validated reference project. Its "
            "inputs and results are held fixed and used as a known-good anchor "
            "for testing the model."
        ),
        metrics=(),
        disclosures=_NOT_ADVICE_ONLY,
        internal_classification="protected synthetic reference",
    )


def _generic_project_status(project_key: str, display_name: str) -> ProjectValidationStatus:
    return ProjectValidationStatus(
        project_key=project_key,
        display_name=display_name,
        tier=ValidationTier.VALIDATED_WITH_CAVEATS,
        tier_label=TIER_LABELS[ValidationTier.VALIDATED_WITH_CAVEATS],
        tier_tone=TIER_TONE[ValidationTier.VALIDATED_WITH_CAVEATS],
        tier_description=(
            f"{display_name} is a validated generic model. Core cost and "
            "revenue figures are validated; debt-service shape and the related "
            "return metrics carry a documented methodology caveat."
        ),
        metrics=_generic_metrics(),
        disclosures=DISCLOSURE_TEXT,
        internal_classification="validated generic bootstrap model with caveats",
    )


def _design_only_project_status(project_key: str, display_name: str) -> ProjectValidationStatus:
    return ProjectValidationStatus(
        project_key=project_key,
        display_name=display_name,
        tier=ValidationTier.DESIGN_ONLY,
        tier_label=TIER_LABELS[ValidationTier.DESIGN_ONLY],
        tier_tone=TIER_TONE[ValidationTier.DESIGN_ONLY],
        tier_description=(
            f"{display_name} is a design-only configuration. It has not been "
            "validated against a reference methodology and is not externally "
            "validated."
        ),
        metrics=(),
        disclosures=_NOT_EXTERNALLY_VALIDATED,
        internal_classification="design-only / not externally validated",
    )


def _experimental_project_status(project_key: str, display_name: str) -> ProjectValidationStatus:
    return ProjectValidationStatus(
        project_key=project_key,
        display_name=display_name,
        tier=ValidationTier.EXPERIMENTAL,
        tier_label=TIER_LABELS[ValidationTier.EXPERIMENTAL],
        tier_tone=TIER_TONE[ValidationTier.EXPERIMENTAL],
        tier_description=(
            f"{display_name} is experimental and for internal use only. It is "
            "not validated and is not intended for external use."
        ),
        metrics=(),
        disclosures=_NOT_EXTERNALLY_VALIDATED,
        internal_classification="experimental / internal only",
    )


_PROJECT_VALIDATION_BUILDERS: dict[str, tuple[str, object]] = {
    "generic_wind_reference": ("Generic Wind Reference", _reference_project_status),
    "generic_solar_reference": ("Generic Solar Reference", _reference_project_status),
    "generic_storage_reference": ("Generic Storage Reference", _design_only_project_status),
    "generic_data_center_reference": ("Generic Data Center Reference", _reference_project_status),
    "generic_data_center": ("Generic Data Center", _generic_project_status),
    "generic_solar": ("Generic Solar", _generic_project_status),
    "generic_wind": ("Generic Wind", _generic_project_status),
    "generic_bess": ("Generic BESS", _design_only_project_status),
    "solar_bess": ("Generic Solar + BESS", _design_only_project_status),
    "wind_bess": ("Generic Wind + BESS", _design_only_project_status),
    "portfolio": ("Portfolio", _experimental_project_status),
}

# Aliases for the various spellings used elsewhere in the codebase
# (project_code values, UI project ids, factory names, etc.).
_PROJECT_KEY_ALIASES: dict[str, str] = {
    "generic_wind_reference": "generic_wind_reference",
    "generic_wind_reference_wind1": "generic_wind_reference",
    "generic_solar_reference": "generic_solar_reference",
    "solar": "generic_solar",
    "generic_solar": "generic_solar",
    "generic-solar": "generic_solar",
    "wind": "generic_wind",
    "generic_wind": "generic_wind",
    "generic-wind": "generic_wind",
    "bess": "generic_bess",
    "generic_bess": "generic_bess",
    "solar_bess": "solar_bess",
    "solar+bess": "solar_bess",
    "wind_bess": "wind_bess",
    "wind+bess": "wind_bess",
    "portfolio": "portfolio",
}


def normalize_project_key(project_key: str) -> str:
    """Normalize any known project identifier spelling to a canonical key."""
    key = (project_key or "").strip().lower().replace(" ", "_")
    return _PROJECT_KEY_ALIASES.get(key, key)


def get_validation_status(project_key: str) -> ProjectValidationStatus:
    """Return the validation status for a project, by any known key spelling.

    Unknown keys are treated as experimental/internal-only rather than
    raising, since this is presentation-only and must never block a
    runtime calculation.
    """
    canonical = normalize_project_key(project_key)
    if canonical not in _PROJECT_VALIDATION_BUILDERS:
        return _experimental_project_status(canonical, project_key or canonical)
    display_name, builder = _PROJECT_VALIDATION_BUILDERS[canonical]
    return builder(canonical, display_name)


def all_validation_statuses() -> tuple[ProjectValidationStatus, ...]:
    """Return validation status for every known project key, in a stable order."""
    return tuple(get_validation_status(key) for key in _PROJECT_VALIDATION_BUILDERS)
