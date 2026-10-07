"""app.v2.smart_panel_projection — contextual Smart Panel presentation.

Presentation-only projection for the right-side Smart Panel (UX Foundation
Phase C).  The panel is NOT a second Assumption Register or a second
analytics engine: it renders availability + navigation rows over EXISTING
authorities and never computes financial values:

- CHECKS      — the repository's own validation-tier authority
                (``app.validation_status``) plus Trust Pack section states.
                Severity is the repository's own tier tone (pass/warn/fail)
                — never remapped, no invented lender rules.  Rows are
                ordered fail → warn → pass (blocking first).
- ASSUMPTIONS — availability + navigation to the Assumption Register on the
                Trust Pack sheet (the register itself stays THE authority).
- TRACE       — availability + navigation to the Calculation Trace surface
                (needs a persisted run; otherwise typed unavailable).

NO engine execution happens in any code path of this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.validation_status import TIER_LABELS, TIER_TONE, get_validation_status

# Repository tone vocabulary → display order (blocking first).
_TONE_ORDER = {"fail": 0, "warn": 1, "pass": 2, "": 3}

TRUST_TAB_ID = "tab-trust"


@dataclass(frozen=True)
class SmartPanelRow:
    label: str
    value: str
    tone: str = ""          # repository tone: "pass" | "warn" | "fail" | ""
    detail: str = ""


@dataclass(frozen=True)
class SmartPanelLink:
    label: str
    tab_id: str
    # Optional in-page anchor inside the target tab panel (e.g.
    # "#assumption-register"); navigation scrolls to it after activating
    # the tab.  Only rendered when the target section actually exists.
    anchor: str = ""


@dataclass(frozen=True)
class SmartPanelSection:
    key: str
    title: str
    available: bool
    rows: tuple[SmartPanelRow, ...]
    empty_text: str = ""
    link: Optional[SmartPanelLink] = None


@dataclass(frozen=True)
class SmartPanelProjection:
    stale_note: str                     # runtime-state note ("" when none)
    run_state: str                      # NOT_RUN | CURRENT | STALE
    sections: tuple[SmartPanelSection, ...]

    @property
    def ordered_rows(self) -> tuple[SmartPanelRow, ...]:
        """All check rows across sections, blocking first (repository tones)."""
        rows: list[SmartPanelRow] = []
        for section in self.sections:
            rows.extend(section.rows)
        return tuple(sorted(rows, key=lambda r: _TONE_ORDER.get(r.tone, 3)))


def _validation_row(project_key: str) -> SmartPanelRow:
    """One CHECKS row from the repository's validation-tier authority.

    Fail-open by design (unknown key → the repository's own EXPERIMENTAL
    tier); the label and tone are the repository's own vocabulary.
    """
    status = get_validation_status(project_key)
    tier = status.tier
    return SmartPanelRow(
        label="Validation tier",
        value=TIER_LABELS.get(tier, str(tier)),
        tone=TIER_TONE.get(tier, ""),
        detail="Reference regression evidence loads on demand in the Trust Pack.",
    )


def build_smart_panel_projection(
    *,
    trust_pack: Optional[dict[str, Any]],
    runtime_state: str,
    has_runtime: bool,
    project_key: str = "",
    assumption_register_view: Optional[dict[str, Any]] = None,
) -> SmartPanelProjection:
    """Build the Smart Panel display payload from existing authorities.

    ``trust_pack`` is the workbook route's already-composed Trust Pack dict
    (its sections fail closed to UNAVAILABLE independently).
    ``assumption_register_view`` is the route's Workflow 04 register view
    (Correction A4/A8): availability is taken from the ACTUAL authority
    construction result — never asserted unconditionally.  The Calculation
    Trace needs the clean production run object, which is not persisted
    after a run and must never be re-executed at render time, so TRACE is
    a typed unavailable/future section.  Nothing here executes the engine
    or the reference validation.
    """
    state = str(runtime_state or "").strip().upper()
    if state == "STALE":
        stale_note = ("Working Copy has changes not yet run — "
                      "Last Run values are stale.")
    elif state == "NOT_RUN":
        stale_note = "Run the model to produce outputs."
    else:
        stale_note = ""

    sections: list[SmartPanelSection] = []

    # ── CHECKS — repository validation tier + Trust Pack section states ──
    check_rows: list[SmartPanelRow] = []
    if project_key:
        check_rows.append(_validation_row(project_key))
    validation: dict[str, Any] = (trust_pack or {}).get("validation", {}) or {}
    if isinstance(validation, dict) and validation:
        state_val = str(validation.get("state", "")).upper()
        check_rows.append(SmartPanelRow(
            label="Reference regression",
            value="AVAILABLE" if state_val == "AVAILABLE"
            else ("LOADS ON DEMAND" if state_val == "DEFERRED"
                  else "UNAVAILABLE"),
            tone="" if state_val == "AVAILABLE" else "warn",
            detail="Loads on demand in the Trust Pack — never run on render.",
        ))
    last_run: dict[str, Any] = (trust_pack or {}).get("last_run", {}) or {}
    if isinstance(last_run, dict) and last_run:
        state_lr = str(last_run.get("state", "")).upper()
        check_rows.append(SmartPanelRow(
            label="Last Run identity",
            value="AVAILABLE" if state_lr == "AVAILABLE" else "UNAVAILABLE",
            tone="" if state_lr == "AVAILABLE" else "warn",
        ))
    if not check_rows:
        check_rows.append(SmartPanelRow(
            label="Checks", value="No checks available yet.", tone=""))
    sections.append(SmartPanelSection(
        key="checks", title="Checks", available=bool(check_rows),
        rows=tuple(check_rows),
        empty_text="No checks available for this project yet.",
        link=SmartPanelLink("Open Trust Pack", TRUST_TAB_ID),
    ))

    # ── ASSUMPTIONS — availability from the ACTUAL Workflow 04 register
    # construction (Correction A4/A8); the register itself stays THE
    # authority — the panel only reports and navigates to it. ─────────────
    register_ok = bool(assumption_register_view
                       and assumption_register_view.get("available"))
    if register_ok:
        sections.append(SmartPanelSection(
            key="assumptions", title="Assumptions", available=True,
            rows=(SmartPanelRow(
                label="Assumption Register",
                value=("Working Copy register · "
                       f"{assumption_register_view.get('entry_count', 0)} entries"),
                detail="Review assumptions against their reference sources.",
            ),),
            empty_text="Assumptions unavailable.",
            link=SmartPanelLink("Review assumptions", TRUST_TAB_ID,
                                anchor="#assumption-register"),
        ))
    else:
        sections.append(SmartPanelSection(
            key="assumptions", title="Assumptions", available=False,
            rows=(),
            empty_text=("Assumption Register unavailable for the current "
                        "Working Copy state."),
            link=None,
        ))

    # ── TRACE — typed unavailable: the full trace is bound to the clean
    # production run object, which is not persisted after a run; loading it
    # on demand would execute the engine.  Honest future surface, no fake
    # navigation. ──────────────────────────────────────────────────────────
    sections.append(SmartPanelSection(
        key="trace", title="Trace", available=False,
        rows=(),
        empty_text=("Full Calculation Trace is not available in this "
                    "surface yet — it requires the clean production run "
                    "object, which is not persisted after a run. "
                    "Derivation lineage is visible in the Trust Pack KPIs "
                    "and the Run Certificate."),
        link=None,
    ))

    return SmartPanelProjection(
        stale_note=stale_note,
        run_state=state if state in ("NOT_RUN", "CURRENT", "STALE") else "NOT_RUN",
        sections=tuple(sections),
    )


__all__ = [
    "SmartPanelLink",
    "SmartPanelProjection",
    "SmartPanelRow",
    "SmartPanelSection",
    "build_smart_panel_projection",
]
