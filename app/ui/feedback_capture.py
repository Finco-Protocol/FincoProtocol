"""Phase 25C-3 — Pilot Feedback Capture.

Pure read-side helper module. Builds a copyable
feedback template for the Generic Solar / Wind
exploratory pilot.

The helper does NOT:
- mutate any input
- call the persistence layer
- call services
- enable any feature flag
- change any runtime path
- touch construction / C10 / R-PAR / tax / debt / IDC
- touch rc1
- touch factory (Generic Wind Reference / Generic Solar Reference)
- invent fake outputs, fake run IDs, fake
  validation claims
- invent fake ticket IDs
- capture PII
- write to a database

The feedback template is a 6-field structured
template:
1. Project name
2. Scenario name (or N/A)
3. What I tried
4. What I expected
5. What happened
6. Screenshot (optional, by attaching to the
   feedback email or chat)

The helper also exposes a SHORT, copyable summary
template (3 lines) for quick in-product feedback.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Field vocabulary
# ---------------------------------------------------------------------------


FIELD_PROJECT = "project"
FIELD_SCENARIO = "scenario"
FIELD_WHAT_I_TRIED = "what_i_tried"
FIELD_WHAT_I_EXPECTED = "what_i_expected"
FIELD_WHAT_HAPPENED = "what_happened"
FIELD_SCREENSHOT = "screenshot"

FIELD_LABELS: dict[str, str] = {
    FIELD_PROJECT: "Project name",
    FIELD_SCENARIO: "Scenario name (or N/A)",
    FIELD_WHAT_I_TRIED: "What I tried",
    FIELD_WHAT_I_EXPECTED: "What I expected",
    FIELD_WHAT_HAPPENED: "What happened",
    FIELD_SCREENSHOT: "Screenshot (optional)",
}

# Stable order.
FIELD_ORDER: tuple[str, ...] = (
    FIELD_PROJECT,
    FIELD_SCENARIO,
    FIELD_WHAT_I_TRIED,
    FIELD_WHAT_I_EXPECTED,
    FIELD_WHAT_HAPPENED,
    FIELD_SCREENSHOT,
)

#: Help text shown below each field.
FIELD_HELP: dict[str, str] = {
    FIELD_PROJECT: (
        "The name of the project you were working on "
        "(e.g. 'My Solar 1')."
    ),
    FIELD_SCENARIO: (
        "The scenario name (e.g. 'Base', 'Downside'), "
        "or N/A if the issue is not scenario-specific."
    ),
    FIELD_WHAT_I_TRIED: (
        "1-3 sentences describing the action you took "
        "(e.g. 'Saved Base scenario, then ran it')."
    ),
    FIELD_WHAT_I_EXPECTED: (
        "1-3 sentences describing what you expected "
        "to happen (e.g. 'A clean run summary with "
        "IRR / DSCR values')."
    ),
    FIELD_WHAT_HAPPENED: (
        "1-3 sentences describing what actually "
        "happened. If you saw an error message, "
        "include its text verbatim (no screenshots "
        "required). DO NOT include secrets."
    ),
    FIELD_SCREENSHOT: (
        "Optional. Attach a screenshot to the "
        "feedback email or chat. DO NOT include "
        "secrets or customer PII in the screenshot."
    ),
}

#: Short summary template (3 lines) for in-product
#: quick feedback.
SHORT_TEMPLATE_LINES: tuple[str, ...] = (
    "Project:",
    "What I tried:",
    "What happened:",
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeedbackField:
    """A single field in the feedback template."""

    key: str
    label: str
    help: str
    order: int


@dataclass(frozen=True)
class FeedbackTemplate:
    """The 6-field feedback template."""

    fields: tuple[FeedbackField, ...]
    short_lines: tuple[str, ...]
    exploratory_disclaimer: str

    def field_count(self) -> int:
        return len(self.fields)


#: Exploratory disclaimer shown at the top of the
#: feedback panel. This is descriptive scope
#: language, not a no-go claim.
EXPLORATORY_DISCLAIMER: str = (
    "This feedback channel is for the Generic "
    "Solar / Generic Wind exploratory pilot only. "
    "It is not a support channel for production "
    "use. DO NOT include secrets or customer PII. "
    "Your feedback is read by humans; it is not "
    "automatically processed."
)


__all__ = [
    "FeedbackField",
    "FeedbackTemplate",
    "FIELD_ORDER",
    "FIELD_LABELS",
    "FIELD_HELP",
    "SHORT_TEMPLATE_LINES",
    "EXPLORATORY_DISCLAIMER",
    "build_feedback_template",
    "is_supported_field",
    "is_short_line",
]


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


def is_supported_field(key: str) -> bool:
    """Return True if the field key is one of the 6
    canonical fields."""
    return key in FIELD_LABELS


def is_short_line(line: str) -> bool:
    """Return True if the line is one of the 3 short
    template lines (without trailing colon)."""
    base = line.rstrip(":").strip()
    return base in (
        "Project",
        "What I tried",
        "What happened",
    )


def build_feedback_template() -> FeedbackTemplate:
    """Build the 6-field feedback template."""
    fields: list[FeedbackField] = []
    for i, key in enumerate(FIELD_ORDER, start=1):
        fields.append(
            FeedbackField(
                key=key,
                label=FIELD_LABELS[key],
                help=FIELD_HELP[key],
                order=i,
            )
        )
    return FeedbackTemplate(
        fields=tuple(fields),
        short_lines=SHORT_TEMPLATE_LINES,
        exploratory_disclaimer=EXPLORATORY_DISCLAIMER,
    )
