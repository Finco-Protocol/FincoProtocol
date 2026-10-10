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
    INTEGRITY_CHECK = "INTEGRITY_CHECK"      # committed Last Run integrity verdict not PASS


from app.v2.kpi_strip_projection import KpiStrip, build_kpi_strip


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
    open: bool = False


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
    group: str = ""         # worklist group (see WORKLIST_GROUPS); presentation only
    group_label: str = ""


# Validation worklist groups — each keeps its own meaning; a group is never merged into
# another and freshness is never an integrity verdict (nor the reverse).
WORKLIST_GROUPS: tuple[tuple[str, str], ...] = (
    ("input", "Economic input errors"),
    ("integrity", "Financial integrity"),
    ("evidence", "Missing assumptions / evidence"),
    ("protected", "Protected / calculated inputs"),
    ("freshness", "Last Run freshness"),
)
_GROUP_OF = {
    SummaryClass.REQUIRED_MISSING: "input",
    SummaryClass.INVALID: "input",
    SummaryClass.OUT_OF_BOUNDS: "input",
    SummaryClass.SAVE_REJECTED: "input",
    SummaryClass.INTEGRITY_CHECK: "integrity",
    SummaryClass.AUTHORITY_UNAVAILABLE: "evidence",
    SummaryClass.NON_EDITABLE: "protected",
    SummaryClass.STALE_LAST_RUN: "freshness",
    SummaryClass.NOT_RUN: "freshness",
}
_GROUP_ORDER = {g: i for i, (g, _l) in enumerate(WORKLIST_GROUPS)}


def _grouped(items: "list[SmartPanelSummaryItem]") -> tuple["SmartPanelSummaryItem", ...]:
    from dataclasses import replace
    labels = dict(WORKLIST_GROUPS)
    tagged = [replace(it, group=_GROUP_OF.get(it.key, ""),
                      group_label=labels.get(_GROUP_OF.get(it.key, ""), ""))
              for it in items]
    return tuple(sorted(tagged, key=lambda it: _GROUP_ORDER.get(it.group, 99)))


@dataclass(frozen=True)
class SmartPanelIssue:
    """One read-only action from an existing and explicit authority status."""

    key: str
    group: str
    label: str
    severity: str                 # fail | warn | info (never an invented verdict)
    detail: str
    source: str
    action: str = ""
    tab_id: str = ""               # only existing workbook tabs


@dataclass(frozen=True)
class SmartPanelProjection:
    stale_note: str                     # runtime-state note ("" when none)
    run_state: str                      # NOT_RUN | CURRENT | STALE
    sections: tuple[SmartPanelSection, ...]
    validation_summary: tuple[SmartPanelSummaryItem, ...] = ()
    kpi_strip: Optional[KpiStrip] = None   # persistent Key-metrics strip (Workflow C)
    issues: tuple[SmartPanelIssue, ...] = ()
    inspector_fields: tuple[dict[str, str], ...] = ()

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
    # Committed Last Run integrity verdict (separate authority): listed only when it is not
    # PASS, with its typed reason codes.  Freshness (CURRENT / STALE) never changes it.
    if isinstance(integrity, dict) and integrity \
            and str(integrity.get("state", "")).upper() == "AVAILABLE":
        overall = str(integrity.get("overall") or "").upper()
        if overall and overall != "PASS":
            row = _integrity_row(integrity)
            items.append(SmartPanelSummaryItem(
                S.INTEGRITY_CHECK, "Run integrity", value=overall,
                tone="fail" if overall == "FAIL" else "warn",
                detail=(row.detail if row is not None else "")
                + " Independent of whether the Last Run is CURRENT or STALE."))
    return _grouped(items)


def _q2_issues(*, trust_pack: dict[str, Any], run_state: str,
               register_ok: bool) -> tuple[SmartPanelIssue, ...]:
    """Q2 Solutions: status-to-action projection, not a bankability engine.

    Only proven statuses become findings.  The absence of a covenant
    threshold cannot be converted into a breach or financial recommendation.
    """
    issues: list[SmartPanelIssue] = []
    integrity = trust_pack.get("integrity")
    if isinstance(integrity, dict) and str(integrity.get("state", "")).upper() == "AVAILABLE":
        verdict = str(integrity.get("overall") or "").upper()
        if verdict in ("FAIL", "INCOMPLETE"):
            row = _integrity_row(integrity)
            issues.append(SmartPanelIssue(
                key="last-run-integrity-" + verdict.lower(),
                group="Financial integrity",
                label="Committed Last Run integrity: " + verdict,
                severity="fail" if verdict == "FAIL" else "warn",
                detail=(row.detail if row else "Review the committed integrity evidence.")
                       + " This verdict applies to the Last Run, not changed Working Copy inputs.",
                source="Trust Pack / Run Integrity",
                action="Inspect Run Integrity", tab_id=TRUST_TAB_ID,
            ))
    elif isinstance(integrity, dict) and integrity:
        issues.append(SmartPanelIssue(
            key="integrity-unavailable", group="Data availability",
            label="Run Integrity not available", severity="info",
            detail="No confirmed Run Integrity verdict is available on this view.",
            source="Trust Pack / Run Integrity",
            action="Open Trust Pack", tab_id=TRUST_TAB_ID,
        ))

    if not register_ok:
        issues.append(SmartPanelIssue(
            key="register-unavailable", group="Missing assumptions",
            label="Assumption Register unavailable", severity="warn",
            detail="Input provenance cannot be inspected until the canonical Working Copy register is available.",
            source="Assumption Register construction",
            action="Open Trust Pack", tab_id=TRUST_TAB_ID,
        ))

    validation = trust_pack.get("validation")
    if isinstance(validation, dict) and validation:
        status = str(validation.get("state") or "").upper()
        if status not in ("AVAILABLE", "DEFERRED"):
            issues.append(SmartPanelIssue(
                key="reference-regression-unavailable", group="Data availability",
                label="Reference regression unavailable", severity="info",
                detail="Availability is not a model failure. The Trust Pack owns this check.",
                source="Trust Pack / Reference regression",
                action="Open Trust Pack", tab_id=TRUST_TAB_ID,
            ))

    if run_state == "STALE":
        issues.append(SmartPanelIssue(
            key="working-copy-stale", group="Working versus Last Run freshness",
            label="Working Copy differs from Last Run", severity="warn",
            detail="Saved inputs changed since the previous Run. Existing KPIs are historical and cannot validate current inputs.",
            source="Canonical runtime freshness",
            action="Review changes",  # mode switch stays a client interaction
        ))
    elif run_state == "NOT_RUN":
        issues.append(SmartPanelIssue(
            key="no-committed-run", group="Project economics",
            label="No committed financial Run", severity="info",
            detail="Financial KPIs and run-bound integrity are unavailable until a user explicitly runs the model.",
            source="Canonical runtime freshness",
        ))

    order = {"fail": 0, "warn": 1, "info": 2}
    return tuple(sorted(issues, key=lambda i: (order[i.severity], i.group, i.key)))


def _q2_inspector_fields(register_view: Optional[dict[str, Any]]) -> tuple[dict[str, str], ...]:
    """Only expose proven register *presentation* fields, never infer IDs.

    The view currently omits assumption_id and full field/KPI lineage.  Q2
    must declare those UNAVAILABLE until canonical bridge authority exists.
    """
    if not isinstance(register_view, dict) or not register_view.get("available"):
        return ()
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in register_view.get("rows") or ():
        if not isinstance(row, dict):
            continue
        path = str(row.get("path") or "")
        if not path or path in seen:
            continue
        seen.add(path)
        result.append({
            "path": path,
            "label": str(row.get("label") or path),
            "section": str(row.get("section") or ""),
            "value": str(row.get("value") if row.get("value") is not None else "UNAVAILABLE"),
            "unit": str(row.get("unit") or ""),
            "source": str(row.get("source") or "UNKNOWN"),
        })
    return tuple(result)


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

    # ── EVIDENCE & LINEAGE — what is actually known about where a displayed number
    # comes from.  Five levels are kept distinct and never blended:
    #   1. exact persisted value   (Key metrics: raw persisted output, hover = source/unit)
    #   2. typed derivation evidence (Trust Pack methodology rows)
    #   3. navigation to the source (metric buttons / links)
    #   4. full Calculation Trace   (see TRACE: unavailable unless genuinely present)
    #   5. unavailable evidence     (listed below; never read as PASS or zero)
    lr_pack: dict[str, Any] = (trust_pack or {}).get("last_run", {}) or {}
    lineage_rows: list[SmartPanelRow] = []
    if isinstance(lr_pack, dict) and str(lr_pack.get("state", "")).upper() == "AVAILABLE":
        bits = []
        if lr_pack.get("snapshot_id"):
            bits.append(f"Snapshot {lr_pack['snapshot_id']}")
        if lr_pack.get("composite_hash_short"):
            bits.append(f"hash {lr_pack['composite_hash_short']}")
        if lr_pack.get("run_at_display"):
            bits.append(str(lr_pack["run_at_display"]))
        if lr_pack.get("engine_version"):
            bits.append(f"engine {lr_pack['engine_version']}")
        lineage_rows.append(SmartPanelRow(
            label="Last Run identity", value="AVAILABLE", detail=" · ".join(bits)))
    else:
        lineage_rows.append(SmartPanelRow(
            label="Last Run identity", value="UNAVAILABLE", tone="warn",
            detail="No committed Last Run: nothing to trace yet."))
    lineage_rows.append(SmartPanelRow(
        label="Exact persisted values", value="Key metrics",
        detail=("Each metric is the raw persisted output (runtime_summary / "
                "sponsor_schedule.summary) formatted without recomputation; hover "
                "a metric for its source and unit.")))
    lineage_rows.append(SmartPanelRow(
        label="Derivation evidence", value="Trust Pack methodology",
        detail="Period timing and sign convention per KPI are listed in the Trust Pack."))
    strip_src = (trust_pack or {}).get("kpi_strip_source") or {}
    gap_rows = [
        SmartPanelRow(label="Project NPV", value="Not persisted",
                      detail="No Last Run value; never derived here."),
        SmartPanelRow(label="Total CFADS", value="Not persisted",
                      detail="No aggregate Last Run value; not summed from periods."),
        SmartPanelRow(label="LCOE", value="No canonical authority",
                      detail="A reviewed authority decision is required first."),
        SmartPanelRow(label="WACC", value="Reserved", detail="No canonical authority yet."),
        SmartPanelRow(label="Payback / discounted payback", value="Reserved",
                      detail="No canonical authority yet."),
    ]

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
        # What IS known instead of a full trace (kept distinct from it, never blended).
        breakdowns=(
            SmartPanelBreakdown("Available evidence (not a full trace)", tuple(lineage_rows)),
            SmartPanelBreakdown("Authority gaps (not persisted, never derived)", tuple(gap_rows)),
        ),
    ))

    run_state = state if state in ("NOT_RUN", "CURRENT", "STALE") else "NOT_RUN"
    pack = trust_pack or {}
    strip_source = pack.get("kpi_strip_source")
    kpi_strip = build_kpi_strip(
        strip_source, runtime_state=run_state,
        integrity=pack.get("integrity"), last_run=pack.get("last_run"),
        scenario_name=str((strip_source or {}).get("run_scenario_name") or ""),
    ) if strip_source is not None else None
    return SmartPanelProjection(
        stale_note=stale_note,
        run_state=run_state,
        sections=tuple(sections),
        validation_summary=_validation_summary(
            run_state=run_state, trust_pack=trust_pack, register_ok=register_ok),
        kpi_strip=kpi_strip,
        issues=_q2_issues(trust_pack=pack, run_state=run_state,
                          register_ok=register_ok),
        inspector_fields=_q2_inspector_fields(assumption_register_view),
    )


__all__ = [
    "SmartPanelBreakdown",
    "SmartPanelIssue",
    "SmartPanelLink",
    "SmartPanelProjection",
    "SmartPanelRow",
    "SmartPanelSection",
    "SmartPanelSummaryItem",
    "SummaryClass",
    "build_smart_panel_projection",
]
