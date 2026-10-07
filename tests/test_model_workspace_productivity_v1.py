"""Model workspace productivity V1 — dense inputs, typed field validation,
jump-to-field plumbing and Smart Panel completion.

PRESENTATION + TYPED CLASSIFICATION ONLY.  Zero financial-semantic changes:
validation/coercion behaviour, canonical values, editability, the engine and
every frozen namespace are untouched.  Browser-behaviour proofs (pending /
saving / failed-save decoration, summary, jump) live in
``tests/test_model_workspace_productivity_v1_browser.py``.
"""
from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import pytest

from model_workspace_harness import (
    TRICKY_VALUES, default_panel, render_macro_rows, render_panel, sheet_fields,
)

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "static/css/workbook_v2.css").read_text(encoding="utf-8")
JS = (ROOT / "static/js/workbook_v2.js").read_text(encoding="utf-8")
SHEETS_UNDER_TEST = ("project_setup", "revenue", "debt", "tax")


class _Tags(HTMLParser):
    """Collect (tag, attrs) for every start tag of a rendered fragment."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, {k: (v if v is not None else "") for k, v in attrs}))


def _tags(html: str) -> list[tuple[str, dict]]:
    parser = _Tags()
    parser.feed(html)
    return parser.tags


def _row(html: str) -> dict:
    return next(attrs for tag, attrs in _tags(html) if "v2-field-row" in attrs.get("class", ""))


# ═══════════════════════════════════════════════════════════════════════════
# 1. Typed field-validation classification
# ═══════════════════════════════════════════════════════════════════════════

class TestTypedFieldClassification:
    @staticmethod
    def _validate(field_id, raw):
        from app.workbook.update_service import WorkbookUpdateService
        return WorkbookUpdateService.validate_field_update(field_id, raw)

    def test_vocabulary_is_exactly_the_three_required_classes(self):
        from app.workbook.update_service import FieldErrorClass
        assert {c.value for c in FieldErrorClass} == {
            "REQUIRED_MISSING", "INVALID", "OUT_OF_BOUNDS"}

    @pytest.mark.parametrize("raw", ["", "   ", "\t"])
    def test_required_missing_includes_whitespace_only(self, raw):
        from app.workbook.update_service import FieldErrorClass
        for field_id in ("project_setup.identity.project_name",
                         "project_setup.technical.construction_months"):
            result = self._validate(field_id, raw)
            assert not result.is_valid
            assert result.error_class is FieldErrorClass.REQUIRED_MISSING

    @pytest.mark.parametrize("field_id,raw", [
        ("project_setup.technical.capacity_mw", "0"),          # below min 0.1
        ("project_setup.technical.capacity_mw", "-5"),
        ("project_setup.technical.p50_hours", "0.5"),          # below min 1
        ("revenue.ppa.index", "101"),                          # above max 100
        ("project_setup.technical.construction_months", "0"),  # int below min
        ("project_setup.technical.construction_months", "121"),
        ("project_setup.technical.horizon_years", "51"),
    ])
    def test_out_of_bounds_low_and_high(self, field_id, raw):
        from app.workbook.update_service import FieldErrorClass
        result = self._validate(field_id, raw)
        assert result.error_class is FieldErrorClass.OUT_OF_BOUNDS
        assert result.typed_value is not None     # coercible; only the range failed

    @pytest.mark.parametrize("field_id,raw", [
        ("project_setup.technical.construction_months", "1.5"),   # strict int
        ("project_setup.technical.horizon_years", "2.5"),
        ("project_setup.technical.capacity_mw", "abc"),
        ("project_setup.technical.capacity_mw", "nan"),
        ("project_setup.technical.capacity_mw", "inf"),
        ("project_setup.identity.country_market", "ZZ"),          # not an option
    ])
    def test_invalid_uncoercible_or_not_an_option(self, field_id, raw):
        from app.workbook.update_service import FieldErrorClass
        assert self._validate(field_id, raw).error_class is FieldErrorClass.INVALID

    @pytest.mark.parametrize("field_id,raw", [
        ("project_setup.technical.capacity_mw", "0.1"),   # exactly min
        ("revenue.ppa.index", "100"),                     # exactly max
        ("revenue.ppa.index", "0"),                       # legitimate zero
        ("project_setup.identity.project_name", "Alpha"),
    ])
    def test_valid_values_carry_no_class(self, field_id, raw):
        result = self._validate(field_id, raw)
        assert result.is_valid and result.error is None and result.error_class is None

    def test_classification_is_deterministic(self):
        probes = [("project_setup.technical.capacity_mw", "0"),
                  ("project_setup.technical.construction_months", "1.5"),
                  ("project_setup.identity.project_name", "")]
        runs = [[self._validate(f, r).error_class for f, r in probes] for _ in range(3)]
        assert runs[0] == runs[1] == runs[2]

    def test_error_and_class_must_be_set_together(self):
        from app.workbook.registry import WORKBOOK
        from app.workbook.update_service import FieldErrorClass, FieldValidationResult
        spec = WORKBOOK.field("project_setup.technical.capacity_mw")
        with pytest.raises(ValueError):
            FieldValidationResult("f", "x", None, spec, error="boom")
        with pytest.raises(ValueError):
            FieldValidationResult("f", "x", None, spec, error_class=FieldErrorClass.INVALID)

    def test_class_is_data_not_derived_from_message_text(self):
        """Replacing the human-readable text never changes the class."""
        from app.workbook.update_service import FieldErrorClass
        result = self._validate("project_setup.technical.capacity_mw", "0")
        reworded = dataclasses.replace(result, error="Totally different wording.")
        assert reworded.error_class is FieldErrorClass.OUT_OF_BOUNDS
        assert not reworded.is_valid

    def test_every_error_site_assigns_an_explicit_enum_literal(self):
        """Source guard: no classification by string inspection."""
        from app.workbook.update_service import WorkbookUpdateService
        source = inspect.getsource(WorkbookUpdateService.validate_field_update)
        errors = len(re.findall(r"\berror=", source))
        literals = len(re.findall(r"error_class=FieldErrorClass\.[A-Z_]+", source))
        assert errors == literals and errors >= 6
        assert not re.search(r"error_class\s*=\s*[^F\s]", source)
        assert not re.search(r"(?:in|startswith|endswith|match|search)\(.*error", source)

    def test_human_readable_text_is_unchanged_presentation(self):
        assert self._validate("project_setup.identity.project_name", "").error == \
            "Project Name is required."
        assert self._validate("project_setup.technical.capacity_mw", "0").error == \
            "Installed Capacity must be ≥ 0.1 (got 0.0)."
        assert self._validate("revenue.ppa.index", "101").error == \
            "PPA Escalation Index must be ≤ 100 (got 101.0)."
        assert self._validate("project_setup.identity.country_market", "ZZ").error.startswith(
            "Country / Market: 'ZZ' is not a valid option. Allowed: XA, XB")

    def test_apply_field_to_pis_carries_the_class(self):
        from app.workbook.input_set import ProjectInputSet
        from app.workbook.registry import WORKBOOK
        from app.workbook.update_service import (
            FieldErrorClass, FieldValidationError, WorkbookUpdateService,
        )
        pis = ProjectInputSet.from_snapshot({}, workbook=WORKBOOK)
        result = self._validate("project_setup.technical.capacity_mw", "0")
        with pytest.raises(FieldValidationError) as caught:
            WorkbookUpdateService.apply_field_to_pis(pis, result)
        assert caught.value.error_class is FieldErrorClass.OUT_OF_BOUNDS
        assert str(caught.value) == result.error

    def test_apply_draft_update_carries_the_class_before_any_persistence(self, monkeypatch):
        import app.persistence.workspace_repository as repo
        import app.ui.protected_reference_service as prot
        from app.workbook.registry import WORKBOOK
        from app.workbook.update_service import (
            FieldErrorClass, FieldValidationError, WorkbookUpdateService,
        )

        def _no_db(*a, **k):
            raise AssertionError("validation failure must precede persistence")

        monkeypatch.setattr(prot, "is_protected_reference", lambda record: False)
        monkeypatch.setattr(repo, "v2_atomic_draft_update", _no_db)
        with pytest.raises(FieldValidationError) as caught:
            WorkbookUpdateService.apply_draft_update(
                ws=SimpleNamespace(user_id="u", project_id="p", draft_snapshot={}),
                field_id="project_setup.technical.construction_months",
                raw_value="1.5", content_hash="h", workbook_version=WORKBOOK.version,
                project_record=SimpleNamespace(project_code="demo"))
        assert caught.value.error_class is FieldErrorClass.INVALID

    def test_authority_gate_rejection_is_not_a_value_classification(self, monkeypatch):
        import app.input_adapter as adapter
        import app.persistence.workspace_repository as repo
        import app.ui.protected_reference_service as prot
        from app.workbook.registry import WORKBOOK
        from app.workbook.update_service import FieldValidationError, WorkbookUpdateService

        def _gate(*a, **k):
            raise ValueError("calibrated schedule cannot honour a scalar edit")

        def _no_db(*a, **k):
            raise AssertionError("gate must reject before the CAS")

        monkeypatch.setattr(prot, "is_protected_reference", lambda record: False)
        monkeypatch.setattr(adapter, "assert_debt_scalar_edit_allowed", _gate)
        monkeypatch.setattr(repo, "v2_atomic_draft_update", _no_db)
        with pytest.raises(FieldValidationError) as caught:
            WorkbookUpdateService.apply_draft_update(
                ws=SimpleNamespace(user_id="u", project_id="p", draft_snapshot={}),
                field_id="debt.senior.interest_rate_pct", raw_value="5.0",
                content_hash="h", workbook_version=WORKBOOK.version,
                project_record=SimpleNamespace(project_code="demo"))
        assert caught.value.error_class is None

    def test_non_editable_authorities_are_still_rejected(self):
        """TEMPLATE_LOCKED / DISPLAY_ONLY / PARTIAL stay non-editable (not a
        validation outcome, so no class)."""
        from app.workbook.registry import WORKBOOK
        from app.workbook.specs import BindingStatus
        from app.workbook.update_service import NonEditableFieldError, WorkbookUpdateService
        seen = set()
        for sheet in WORKBOOK.sheets:
            for section in sheet.sections:
                for spec in section.fields:
                    if spec.binding_status in (BindingStatus.TEMPLATE_LOCKED,
                                               BindingStatus.DISPLAY_ONLY,
                                               BindingStatus.PARTIAL):
                        with pytest.raises(NonEditableFieldError):
                            WorkbookUpdateService.validate_field_update(spec.field_id, "1")
                        seen.add(spec.binding_status)
        assert seen == {BindingStatus.TEMPLATE_LOCKED, BindingStatus.DISPLAY_ONLY,
                        BindingStatus.PARTIAL}


# ═══════════════════════════════════════════════════════════════════════════
# 2. Dense layout leaves identity, wiring, values and editability untouched
# ═══════════════════════════════════════════════════════════════════════════

_ADDED_ATTRS = re.compile(r'\s+data-(?:field-label|sheet-id|required)="[^"]*"')


def _normalise(html: str, *, strip_added: bool) -> str:
    if strip_added:
        html = _ADDED_ATTRS.sub("", html)
    return re.sub(r"\s+", " ", html).strip()


class TestDenseLayoutPreservesContract:
    def test_macro_output_matches_the_base_commit_except_three_additive_attributes(self):
        golden = json.loads(
            (ROOT / "tests/fixtures/model_workspace_field_editor_golden.json")
            .read_text(encoding="utf-8"))
        assert golden["base_commit"] == "1951e26df9305edaa4cec3d0066af9fd2ec48fb9"
        actual: dict[str, str] = {}
        for sheet in SHEETS_UNDER_TEST:
            for editable in (True, False):
                rows = render_macro_rows(sheet, project_editable=editable, values=TRICKY_VALUES)
                for field_id, html in rows.items():
                    key = f"{sheet}|{'editable' if editable else 'protected'}|{field_id}"
                    actual[key] = hashlib.sha256(
                        _normalise(html, strip_added=True).encode()).hexdigest()
        assert set(actual) == set(golden["hashes"])
        drifted = sorted(k for k, v in actual.items() if golden["hashes"][k] != v)
        assert not drifted, f"macro DOM identity drifted for: {drifted}"

    @pytest.mark.parametrize("sheet_id", SHEETS_UNDER_TEST)
    def test_semantic_ids_wiring_and_addresses_are_unchanged(self, sheet_id):
        from model_workspace_harness import SHEETS
        dom_id = next(s[1] for s in SHEETS if s[0] == sheet_id)
        fields = {f["field_id"]: f for f in sheet_fields(sheet_id)}
        rows = render_macro_rows(sheet_id, project_editable=True)
        assert set(rows) == set(fields)
        for field_id, html in rows.items():
            tags = _tags(html)
            assert _row(html)["data-field-id"] == field_id
            addrs = [a["data-fc-addr"] for _, a in tags if "data-fc-addr" in a]
            assert addrs == [f"{sheet_id}.{field_id}.label", f"{sheet_id}.{field_id}.value"]
            if fields[field_id]["binding_label"] == "bound":
                form = next(a for t, a in tags if t == "form")
                assert form["hx-post"] == "/v2/workbook/update"
                assert form["hx-target"] == f"#{dom_id}"
                assert form["hx-swap"] == "outerHTML"
                hidden = {a["name"]: a["value"] for t, a in tags
                          if t == "input" and a.get("type") == "hidden"}
                assert hidden["field_id"] == field_id
                assert hidden["sheet_id"] == sheet_id
                assert sum(1 for t, a in tags
                           if t in ("input", "select") and a.get("name") == "value") == 1

    @pytest.mark.parametrize("sheet_id", SHEETS_UNDER_TEST)
    def test_new_attributes_mirror_the_registry(self, sheet_id):
        from app.workbook.registry import WORKBOOK
        for field_id, html in render_macro_rows(sheet_id).items():
            row = _row(html)
            spec = WORKBOOK.field(field_id)
            assert row["data-field-label"] == spec.label
            assert row["data-sheet-id"] == sheet_id
            assert ("data-required" in row) == bool(spec.required)

    def test_canonical_values_render_bit_identically(self):
        rows = {}
        for sheet in SHEETS_UNDER_TEST:
            rows.update(render_macro_rows(sheet, project_editable=True, values=TRICKY_VALUES))
        checked = 0
        for field_id, value in TRICKY_VALUES.items():
            control = next(a for t, a in _tags(rows[field_id])
                           if t == "input" and a.get("name") == "value")
            assert control["value"] == str(value)
            assert control["data-original-value"] == str(value)
            checked += 1
        assert checked == len(TRICKY_VALUES)

    @pytest.mark.parametrize("sheet_id", SHEETS_UNDER_TEST)
    def test_no_field_becomes_editable_because_of_presentation(self, sheet_id):
        fields = {f["field_id"]: f for f in sheet_fields(sheet_id)}
        for field_id, html in render_macro_rows(sheet_id, project_editable=True).items():
            names = [t for t, _ in _tags(html)]
            editable = fields[field_id]["binding_label"] == "bound"
            assert ("v2-field-editable" in _row(html)["class"]) is editable
            assert ("form" in names) is editable
            if not editable:
                assert not {"input", "select", "textarea", "button"} & set(names)

    @pytest.mark.parametrize("sheet_id", SHEETS_UNDER_TEST)
    def test_protected_reference_stays_fully_protected(self, sheet_id):
        for html in render_macro_rows(sheet_id, project_editable=False).values():
            names = {t for t, _ in _tags(html)}
            assert not {"form", "input", "select", "textarea", "button"} & names
            assert "v2-field-readonly" in _row(html)["class"]
            assert _row(html)["data-fc-row"] == "" and "data-field-id" in _row(html)

    @pytest.mark.parametrize("binding", ["template-locked", "display-only", "partial"])
    def test_locked_calculated_and_partial_rows_stay_read_only_with_their_binding(self, binding):
        rows = render_macro_rows("project_setup", project_editable=True)
        by_binding = {f["field_id"]: f["binding_label"] for f in sheet_fields("project_setup")}
        field_id = next(i for i, b in by_binding.items() if b == binding)
        html = rows[field_id]
        row = _row(html)
        assert row["data-binding"] == binding
        assert "v2-field-readonly" in row["class"] and "v2-field-editable" not in row["class"]
        assert f"v2-binding-{binding}" in html                      # binding badge class kept
        assert not {"form", "input", "select", "textarea", "button"} & {t for t, _ in _tags(html)}


# ═══════════════════════════════════════════════════════════════════════════
# 3. CSS / JS static contracts (no second transport, no string classification)
# ═══════════════════════════════════════════════════════════════════════════

class TestStaticAssetContracts:
    @pytest.mark.parametrize("state", ["pending", "saving", "error"])
    def test_each_browser_state_class_has_a_visual_treatment(self, state):
        assert re.search(rf"\.v2-field-row\.v2-field-{state}[^{{]*\{{[^}}]*\S", CSS), state

    def test_states_are_not_colour_only(self):
        for text in ("Unsaved", "Saving…", "Not saved"):
            assert f'content: "{text}"' in CSS
        assert "border-style: dashed" in CSS          # pending pattern cue
        assert "animation: v2-field-saving-sweep" in CSS  # saving motion cue

    def test_dark_theme_and_reduced_motion_are_covered(self):
        assert re.search(r':root\[data-theme="dark"\]\s*\{[^}]*--v2-st-error', CSS)
        assert "prefers-color-scheme: dark" in CSS
        assert "prefers-reduced-motion: reduce" in CSS

    def test_dense_rules_only_target_macro_rows(self):
        block = CSS.split("Workspace productivity v1", 1)[1]
        for selector in re.findall(r"([^{}]+)\{", block):
            for part in selector.split(","):
                part = part.strip()
                if ".v2-field-row" in part and "@" not in part:
                    assert "[data-fc-row]" in part or ".v2-field-pending" in part \
                        or ".v2-field-saving" in part or ".v2-field-error" in part \
                        or ".v2-field-jump-highlight" in part, part

    def test_no_dense_rule_hides_or_disables_controls(self):
        block = CSS.split("Workspace productivity v1", 1)[1]
        assert not re.search(r"\.v2-field-(input|save)[^{]*\{[^}]*display:\s*none", block)
        assert "pointer-events: none" not in block

    def test_classifier_never_reads_the_message_or_parses_strings(self):
        body = JS.split("function classify(input, row)", 1)[1].split("function _classifySubmitted", 1)[0]
        assert "message" not in body
        assert not re.search(r"\.(indexOf|match|test|includes|search|startsWith)\(", body)
        assert "validity" in body

    def test_new_module_reuses_existing_transport_and_adds_none(self):
        module = JS.split("Workspace productivity v1: field validation UX", 1)[1]
        code = re.sub(r"//[^\n]*", "", module)          # comments may name the transport
        for forbidden in ("fetch(", "XMLHttpRequest", "htmx.ajax(", "sendBeacon", "WebSocket",
                          "HX-Trigger", "setRequestHeader"):
            assert forbidden not in code
        assert "workbook-field-error" in JS and "workbook-field-saved" in JS

    def test_jump_uses_the_existing_c1_modules_and_opens_details(self):
        module = JS.split("Workspace productivity v1: field validation UX", 1)[1]
        for needle in ("FcGridRegistry.getAddr", "FcActiveCellManager.setActiveCell",
                       "FcFocusManager.syncFocus", "node.open = true", "scrollIntoView",
                       "v2-field-jump-highlight", "aria-controls"):
            assert needle in module, needle

    def test_error_attachment_is_limited_to_editable_rows(self):
        assert "classList.contains('v2-field-editable')" in JS


# ═══════════════════════════════════════════════════════════════════════════
# 4. Smart Panel: typed summary, enrichment, authority separation
# ═══════════════════════════════════════════════════════════════════════════

def _items(panel):
    return {i.key.value: i for i in panel.validation_summary}


class TestSmartPanelValidationSummary:
    def test_input_classes_match_the_typed_server_classification(self):
        from app.v2.smart_panel_projection import SummaryClass
        from app.workbook.update_service import FieldErrorClass
        assert {c.value for c in FieldErrorClass} <= {c.value for c in SummaryClass}

    def test_classes_are_distinct_never_one_generic_warning(self):
        items = _items(default_panel(runtime_state="STALE"))
        for key in ("REQUIRED_MISSING", "INVALID", "OUT_OF_BOUNDS", "SAVE_REJECTED",
                    "NON_EDITABLE", "STALE_LAST_RUN", "AUTHORITY_UNAVAILABLE"):
            assert key in items or key == "AUTHORITY_UNAVAILABLE"
        labels = [i.label for i in default_panel().validation_summary]
        assert len(labels) == len(set(labels))
        assert items["REQUIRED_MISSING"].label != items["INVALID"].label != items["OUT_OF_BOUNDS"].label

    def test_field_classes_are_live_and_start_empty_not_zero(self):
        items = _items(default_panel())
        for key in ("REQUIRED_MISSING", "INVALID", "OUT_OF_BOUNDS", "SAVE_REJECTED", "NON_EDITABLE"):
            assert items[key].live is True and items[key].value == ""   # missing != zero
        html = render_panel(default_panel())
        for key in ("REQUIRED_MISSING", "INVALID", "OUT_OF_BOUNDS", "SAVE_REJECTED"):
            assert re.search(rf'data-summary-class="{key}"[^>]*\bhidden\b', html), key
        assert "No rejected edits in this session." in html

    def test_stale_last_run_is_not_an_input_error(self):
        register = {"available": True, "entry_count": 1}
        stale = _items(default_panel(runtime_state="STALE", assumption_register_view=register))
        assert stale["STALE_LAST_RUN"].value == "STALE"
        assert "not an input error" in stale["STALE_LAST_RUN"].detail
        assert "AUTHORITY_UNAVAILABLE" not in stale          # stale != unavailable
        current = _items(default_panel(runtime_state="CURRENT", assumption_register_view=register))
        assert "STALE_LAST_RUN" not in current and "NOT_RUN" not in current
        not_run = _items(default_panel(runtime_state="NOT_RUN", has_runtime=False,
                                       assumption_register_view=register))
        assert "STALE_LAST_RUN" not in not_run
        assert not_run["NOT_RUN"].value == "Not run"

    def test_unavailable_authority_is_its_own_class_not_a_validation_error(self):
        from app.workbook.update_service import FieldErrorClass
        panel = default_panel(
            trust_pack={"last_run": {"state": "UNAVAILABLE"},
                        "validation": {"state": "UNAVAILABLE"},
                        "integrity": {"state": "UNAVAILABLE"}},
            assumption_register_view={"available": False, "entry_count": 0})
        item = _items(panel)["AUTHORITY_UNAVAILABLE"]
        assert item.value == "4"
        for name in ("Assumption Register", "Last Run identity",
                     "Reference regression", "Run integrity"):
            assert name in item.detail
        assert "AUTHORITY_UNAVAILABLE" not in {c.value for c in FieldErrorClass}
        assert "not a validation error" in item.detail

    def test_available_or_deferred_authorities_are_not_flagged(self):
        panel = default_panel(
            trust_pack={"last_run": {"state": "AVAILABLE"},
                        "validation": {"state": "DEFERRED"},
                        "integrity": {"state": "AVAILABLE", "overall": "PASS", "counts": {}, "checks": []}},
            assumption_register_view={"available": True, "entry_count": 1})
        assert "AUTHORITY_UNAVAILABLE" not in _items(panel)

    def test_no_failed_execution_state_is_invented(self):
        """The runtime authority emits only NOT_RUN / CURRENT / STALE; nothing
        here may fabricate a failed-run class."""
        from app.v2.smart_panel_projection import SummaryClass
        assert not [c for c in SummaryClass if "FAIL" in c.value and c.value != "SAVE_REJECTED"]
        assert default_panel(runtime_state="FAILED").run_state == "NOT_RUN"

    def test_integrity_reason_codes_counts_and_tone(self):
        panel = default_panel(trust_pack={"integrity": {
            "state": "AVAILABLE", "overall": "FAIL",
            "counts": {"PASS": 5, "FAIL": 1, "UNAVAILABLE": 2},
            "checks": [
                {"status": "FAIL", "reason_code": "CFADS_IDENTITY_MISMATCH"},
                {"status": "UNAVAILABLE", "reason_code": "NO_DEBT_SCHEDULE"},
                {"status": "PASS", "reason_code": None},
            ]}})
        row = {r.label: r for r in panel.sections[0].rows}["Run integrity"]
        assert row.value == "FAIL" and row.tone == "fail"
        assert "PASS 5 · FAIL 1 · UNAVAILABLE 2" in row.detail
        assert "N/A" not in row.detail                       # missing count omitted, not zero
        assert "CFADS_IDENTITY_MISMATCH" in row.detail and "NO_DEBT_SCHEDULE" in row.detail

    def test_integrity_overall_tone_mapping_is_not_remapped(self):
        for overall, tone in (("PASS", "pass"), ("FAIL", "fail"), ("INCOMPLETE", "warn")):
            panel = default_panel(trust_pack={"integrity": {
                "state": "AVAILABLE", "overall": overall, "counts": {}, "checks": []}})
            assert {r.label: r for r in panel.sections[0].rows}["Run integrity"].tone == tone

    def test_validation_tier_uses_the_existing_tier_description(self):
        from app.validation_status import get_validation_status
        panel = default_panel(project_key="solar")
        row = {r.label: r for r in panel.sections[0].rows}["Validation tier"]
        assert row.detail == get_validation_status("solar").tier_description

    def test_summary_changes_nothing_in_the_existing_section_contract(self):
        panel = default_panel(assumption_register_view={"available": True, "entry_count": 24})
        assert [s.key for s in panel.sections] == ["checks", "assumptions", "trace"]
        trace = panel.sections[-1]
        assert trace.available is False and trace.link is None
        assert "not persisted after a run" in trace.empty_text


class TestAssumptionBreakdowns:
    ROWS = (
        [{"section": "Revenue", "source": "User input", "value": "SECRET-A"}] * 3
        + [{"section": "Capex", "source": "Reference", "value": "SECRET-B"}] * 2
        + [{"section": "Tax", "source": "User input", "value": "SECRET-C"}]
    )

    def _panel(self, rows=None):
        rows = self.ROWS if rows is None else rows
        return default_panel(assumption_register_view={
            "available": True, "entry_count": len(rows), "rows": rows})

    def test_counts_are_pure_label_counts(self):
        sec, src = self._panel().sections[1].breakdowns
        assert (sec.title, src.title) == ("By section", "By source")
        assert [(r.label, r.value) for r in sec.rows] == [("Revenue", "3"), ("Capex", "2"), ("Tax", "1")]
        assert [(r.label, r.value) for r in src.rows] == [("User input", "4"), ("Reference", "2")]
        assert sum(int(r.value) for r in sec.rows) == len(self.ROWS)

    def test_panel_is_not_a_second_assumption_authority(self):
        panel = self._panel()
        html = render_panel(panel)
        for secret in ("SECRET-A", "SECRET-B", "SECRET-C"):
            assert secret not in html                         # values never shown
        names = {t for t, _ in _tags(html)}
        assert not {"form", "input", "select", "textarea"} & names   # no duplicate editable forms
        assert "6 entries" in panel.sections[1].rows[0].value        # entry_count untouched

    def test_cap_and_remainder_row(self):
        rows = [{"section": f"S{i:02d}", "source": "x"} for i in range(11)]
        sec = self._panel(rows).sections[1].breakdowns[0].rows
        assert len(sec) == 9 and sec[-1].label == "3 more" and sec[-1].value == "3"

    def test_unavailable_or_row_less_register_has_no_breakdowns(self):
        assert default_panel(assumption_register_view={"available": True, "entry_count": 24}
                             ).sections[1].breakdowns == ()
        assert default_panel(assumption_register_view={"available": False, "entry_count": 0, "rows": self.ROWS}
                             ).sections[1].breakdowns == ()

    def test_unspecified_labels_stay_visible_not_dropped(self):
        rows = [{"section": "Revenue"}, {"section": "Revenue", "source": ""}]
        src = self._panel(rows).sections[1].breakdowns[1].rows
        assert [(r.label, r.value) for r in src] == [("Unspecified", "2")]


class TestSmartPanelTemplate:
    def test_summary_section_and_links_render_without_fake_navigation(self):
        html = render_panel(default_panel(runtime_state="STALE"))
        assert 'data-testid="smart-panel-section-validation"' in html
        assert 'data-testid="smart-panel-summary-stale-last-run"' in html
        assert "Go to field" not in html and "data-jump-field" not in html
        assert 'data-nav-tab="tab-trust"' in html

    def test_breakdowns_render_as_collapsed_details(self):
        html = render_panel(default_panel(assumption_register_view={
            "available": True, "entry_count": 1, "rows": [{"section": "Revenue", "source": "User"}]}))
        assert 'data-testid="smart-panel-breakdown-by-section"' in html
        assert 'data-testid="smart-panel-breakdown-by-source"' in html
        assert not re.search(r"<details[^>]*\bopen\b", html)

    def test_panel_never_contains_editable_controls(self):
        names = {t for t, _ in _tags(render_panel(default_panel(runtime_state="STALE")))}
        assert not {"form", "input", "select", "textarea"} & names


# ═══════════════════════════════════════════════════════════════════════════
# 5. No engine on render; governance
# ═══════════════════════════════════════════════════════════════════════════

class TestNoEngineAndGovernance:
    def test_building_and_rendering_everything_never_runs_the_engine(self, monkeypatch):
        import app.api.project_runner as runner
        from model_workspace_harness import build_page

        def _boom(*a, **k):
            raise AssertionError("engine executed during render")

        monkeypatch.setattr(runner, "run_project", _boom, raising=False)
        build_page(panel=default_panel(
            trust_pack={"last_run": {"state": "AVAILABLE"}}, runtime_state="STALE"))

    def test_retired_epic_scope_marker_is_not_recreated(self):
        assert not (ROOT / "docs/model_v2/ACTIVE_EPIC_SCOPE.json").exists()

    def test_validation_summary_module_has_no_engine_or_financial_imports(self):
        source = (ROOT / "app/v2/smart_panel_projection.py").read_text(encoding="utf-8")
        for forbidden in ("financial_engine", "finco_core", "run_project", "project_runner"):
            assert forbidden not in source
