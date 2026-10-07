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
- VALIDATION  — a typed summary that keeps invalid / missing-required /
                out-of-bounds input, rejected saves, read-only fields,
                unavailable authorities and STALE Last Run as DISTINCT
                classes.  Field-level classes are "live": the browser fills
                them from the rows the sheets actually rendered and rejected
                (jump-to-field targets the existing semantic field); this
                module never validates, never edits and never computes values.

Assumption breakdowns count the register view's own ``section``/``source``
labels — no values are shown, so the panel is not a second assumption
authority.  A failed-execution state is NOT available to this surface (the
runtime authority only emits NOT_RUN / CURRENT / STALE), so none is invented.

NO engine execution happens in any code path of this module.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Optional

from app.validation_status import TIER_LABELS, TIER_TONE, get_validation_status

# Repository tone vocabulary → display order (blocking first).
_TONE_ORDER = {"fail": 0, "warn": 1, "pass": 2, "": 3}

TRUST_TAB_ID = "tab-trust"

_BREAKDOWN_CAP = 8


class SummaryClass(str, Enum):
    """Distinct validation-summary classes (never collapsed into one warning).

    The first three values are identical to ``FieldErrorClass`` in
    ``app.workbook.update_service`` — the typed server classification.
    """
    REQUIRED_MISSING = "REQUIRED_MISSING"
    INVALID = "INVALID"
    OUT_OF_BOUNDS = "OUT_OF_BOUNDS"
    SAVE_REJECTED = "SAVE_REJECTED"          # refused, but not a typed value check
    NON_EDITABLE = "NON_EDITABLE"            # locked / calculated / protected rows
    AUTHORITY_UNAVAILABLE = "AUTHORITY_UNAVAILABLE"
    STALE_LAST_RUN = "STALE_LAST_RUN"
    NOT_RUN = "NOT_RUN"


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
class SmartPanelBreakdown:
    title: str
    rows: tuple[SmartPanelRow, ...]


@dataclass(frozen=True)
class SmartPanelSection:
    key: str
    title: str
    available: bool
    rows: tuple[SmartPanelRow, ...]
    empty_text: str = ""
    link: Optional[SmartPanelLink] = None
    breakdowns: tuple[SmartPanelBreakdown, ...] = ()


@dataclass(frozen=True)
class SmartPanelSummaryItem:
    key: SummaryClass
    label: str
    live: bool = False      # True: count + field list are filled by the browser
    value: str = ""         # static value for server-composed items
    tone: str = ""          # repository tone vocabulary
    detail: str = ""


@dataclass(frozen=True)
class SmartPanelProjection:
    stale_note: str                     # runtime-state note ("" when none)
    run_state: str                      # NOT_RUN | CURRENT | STALE
    sections: tuple[SmartPanelSection, ...]
    validation_summary: tuple[SmartPanelSummaryItem, ...] = ()

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
        detail=status.tier_description,
    )


def _top_counts(rows: Iterable[dict[str, Any]], key: str) -> tuple[SmartPanelRow, ...]:
    """Count the register view's own labels; no values, no recomputation."""
    counts = Counter(str(r.get(key) or "Unspecified") for r in rows if isinstance(r, dict))
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    shown = ordered[:_BREAKDOWN_CAP]
    out = [SmartPanelRow(label=name, value=str(n)) for name, n in shown]
    rest = ordered[_BREAKDOWN_CAP:]
    if rest:
        out.append(SmartPanelRow(
            label=f"{len(rest)} more", value=str(sum(n for _, n in rest))))
    return tuple(out)


def _integrity_row(integrity: Any) -> Optional[SmartPanelRow]:
    """Run Integrity (H-4b) overall + typed reason codes, as composed."""
    if not isinstance(integrity, dict) or not integrity:
        return None
    if str(integrity.get("state", "")).upper() != "AVAILABLE":
        return SmartPanelRow(
            label="Run integrity", value="UNAVAILABLE", tone="warn",
            detail="Internal-consistency checks need a committed Last Run.")
    overall = str(integrity.get("overall") or "").upper()
    tone = {"PASS": "pass", "FAIL": "fail", "INCOMPLETE": "warn"}.get(overall, "warn")
    counts = integrity.get("counts") or {}
    parts = [f"{short} {counts[key]}" for key, short in (
        ("PASS", "PASS"), ("FAIL", "FAIL"),
        ("NOT_APPLICABLE", "N/A"), ("UNAVAILABLE", "UNAVAILABLE"))
        if isinstance(counts, dict) and key in counts]
    codes = sorted({
        str(c.get("reason_code")) for c in (integrity.get("checks") or [])
        if isinstance(c, dict) and c.get("reason_code")
        and str(c.get("status", "")).upper() in ("FAIL", "UNAVAILABLE")
    })[:4]
    if codes:
        parts.append("Reason codes: " + ", ".join(codes))
    return SmartPanelRow(
        label="Run integrity", value=overall or "UNAVAILABLE", tone=tone,
        detail=" · ".join(parts))


def _validation_summary(
    *, run_state: str, trust_pack: Optional[dict[str, Any]], register_ok: bool,
) -> tuple[SmartPanelSummaryItem, ...]:
    S = SummaryClass
    items: list[SmartPanelSummaryItem] = [
        SmartPanelSummaryItem(
            S.REQUIRED_MISSING, "Missing required input", live=True, tone="fail",
            detail="A required field was saved empty."),
        SmartPanelSummaryItem(
            S.INVALID, "Invalid input", live=True, tone="fail",
            detail="The value is not a valid number, date or option."),
        SmartPanelSummaryItem(
            S.OUT_OF_BOUNDS, "Out-of-bounds input", live=True, tone="fail",
            detail="The value is outside the allowed range for the field."),
        SmartPanelSummaryItem(
            S.SAVE_REJECTED, "Save rejected", live=True, tone="warn",
            detail=("Declined for a reason other than a value check, e.g. the "
                    "draft changed since the page loaded or the project is "
                    "protected. Not an input error.")),
        SmartPanelSummaryItem(
            S.NON_EDITABLE, "Read-only fields", live=True,
            detail="Locked by the template, calculated, or protected — not validation errors."),
    ]
    if run_state == "STALE":
        items.append(SmartPanelSummaryItem(
            S.STALE_LAST_RUN, "Last Run", value="STALE", tone="warn",
            detail=("Working Copy changed since the last run, so Last Run "
                    "values are stale. This is not an input error.")))
    elif run_state == "NOT_RUN":
        items.append(SmartPanelSummaryItem(
            S.NOT_RUN, "Last Run", value="Not run",
            detail="No Last Run exists yet; no output values are shown."))

    unavailable: list[str] = []
    if not register_ok:
        unavailable.append("Assumption Register")
    pack = trust_pack or {}
    last_run = pack.get("last_run")
    if isinstance(last_run, dict) and last_run \
            and str(last_run.get("state", "")).upper() != "AVAILABLE":
        unavailable.append("Last Run identity")
    validation = pack.get("validation")
    if isinstance(validation, dict) and validation \
            and str(validation.get("state", "")).upper() not in ("AVAILABLE", "DEFERRED"):
        unavailable.append("Reference regression")
    integrity = pack.get("integrity")
    if isinstance(integrity, dict) and integrity \
            and str(integrity.get("state", "")).upper() != "AVAILABLE":
        unavailable.append("Run integrity")
    if unavailable:
        items.append(SmartPanelSummaryItem(
            S.AUTHORITY_UNAVAILABLE, "Authority unavailable",
            value=str(len(unavailable)), tone="warn",
            detail=", ".join(unavailable) + ". Unavailable is not a validation error."))
    return tuple(items)


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
    integrity_row = _integrity_row((trust_pack or {}).get("integrity"))
    if integrity_row is not None:
        check_rows.append(integrity_row)
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
        register_rows = assumption_register_view.get("rows") or []
        breakdowns: tuple[SmartPanelBreakdown, ...] = ()
        if register_rows:
            breakdowns = (
                SmartPanelBreakdown("By section", _top_counts(register_rows, "section")),
                SmartPanelBreakdown("By source", _top_counts(register_rows, "source")),
            )
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
            breakdowns=breakdowns,
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

    run_state = state if state in ("NOT_RUN", "CURRENT", "STALE") else "NOT_RUN"
    return SmartPanelProjection(
        stale_note=stale_note,
        run_state=run_state,
        sections=tuple(sections),
        validation_summary=_validation_summary(
            run_state=run_state, trust_pack=trust_pack, register_ok=register_ok),
    )


__all__ = [
    "SmartPanelBreakdown",
    "SmartPanelLink",
    "SmartPanelProjection",
    "SmartPanelRow",
    "SmartPanelSection",
    "SmartPanelSummaryItem",
    "SummaryClass",
    "build_smart_panel_projection",
]
