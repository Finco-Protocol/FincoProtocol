"""Model workspace productivity V1 — real-browser behaviour proofs.

Renders the REAL macro / sheet markup / Smart Panel partial with the REAL
``workbook_v2.css`` + ``workbook_v2.js`` and the C1 interaction modules in
production load order (see ``model_workspace_harness``).  HTMX itself is not
loaded: the server round-trip is simulated by dispatching the same DOM events
HTMX would (``htmx:beforeRequest`` → ``workbook-field-error`` / ``-saved``
HX-Trigger events → sheet ``outerHTML`` swap → ``htmx:afterSwap``).  The page
loads no network resources and never executes the engine.

Set ``FINCO_TEST_CHROMIUM_PATH`` to use a specific Chromium binary.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")
from playwright.sync_api import sync_playwright  # noqa: E402

from model_workspace_harness import SHEETS, build_page, default_panel, render_sheet  # noqa: E402

CAPACITY = "project_setup.technical.capacity_mw"          # numeric, min 0.1
P50 = "project_setup.technical.p50_hours"                 # numeric, min 1
NAME = "project_setup.identity.project_name"              # text, required
MONTHS = "project_setup.technical.construction_months"    # int, required, 1..120
INDEX = "revenue.ppa.index"                               # numeric 0..100 (revenue sheet)
LOCKED = "project_setup.identity.project_type"            # TEMPLATE_LOCKED
DOM_ID = {s[0]: s[1] for s in SHEETS}
SHEET_OF = {NAME: "project_setup", MONTHS: "project_setup", CAPACITY: "project_setup",
            P50: "project_setup", LOCKED: "project_setup", INDEX: "revenue"}


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        options = {"args": ["--no-sandbox"]}
        exe = os.environ.get("FINCO_TEST_CHROMIUM_PATH")
        if exe:
            options["executable_path"] = exe
        instance = pw.chromium.launch(**options)
        yield instance
        instance.close()


@pytest.fixture
def make_page(browser):
    opened = []

    def _make(*, width=1440, height=900, **page_kwargs):
        context = browser.new_context(viewport={"width": width, "height": height})
        page = context.new_page()
        page.js_errors = []
        page.network = []
        page.on("pageerror", lambda exc: page.js_errors.append(str(exc)))
        page.on("request", lambda req: page.network.append(req.url))
        page.set_content(build_page(**page_kwargs))
        page.network.clear()                       # only post-load traffic matters
        opened.append(context)
        return page

    yield _make
    for context in opened:
        context.close()


# ── server round-trip simulation ───────────────────────────────────────────

def row(field_id):
    return f'.v2-field-row[data-field-id="{field_id}"]'


def control(field_id):
    return f'{row(field_id)} .v2-field-input'


def _swap(page, sheet_id):
    page.evaluate(
        """([domId, html]) => {
            document.getElementById(domId).outerHTML = html;
            if (window.FcGridRegistry) FcGridRegistry.scanAll();
            document.dispatchEvent(new CustomEvent('htmx:afterSwap', {detail: {}}));
            document.dispatchEvent(new CustomEvent('htmx:afterSettle', {detail: {}}));
        }""",
        [DOM_ID[sheet_id], render_sheet(sheet_id)])


def begin_save(page, field_id):
    page.evaluate(
        """fid => {
            const form = document.querySelector('.v2-field-row[data-field-id="' + fid + '"] form');
            document.dispatchEvent(new CustomEvent('htmx:beforeRequest', {detail: {elt: form}}));
        }""", field_id)


def type_and_submit(page, field_id, raw):
    page.evaluate(
        """([fid, raw]) => {
            const input = document.querySelector('.v2-field-row[data-field-id="' + fid + '"] .v2-field-input');
            input.value = raw;
        }""", [field_id, raw])
    begin_save(page, field_id)


def server_rejects(page, field_id, message="Rejected by the server."):
    """HX-Trigger fires before the swap; the sheet then re-renders persisted values."""
    page.evaluate(
        """([fid, message]) => document.dispatchEvent(new CustomEvent(
            'workbook-field-error', {detail: {field_id: fid, message: message}}))""",
        [field_id, message])
    _swap(page, SHEET_OF[field_id])


def server_accepts(page, field_id, new_hash="hash-1"):
    page.evaluate(
        """([fid, hash]) => document.dispatchEvent(new CustomEvent(
            'workbook-field-saved', {detail: {field_id: fid, new_hash: hash}}))""",
        [field_id, new_hash])
    _swap(page, SHEET_OF[field_id])


def state(page):
    return page.evaluate("v2FieldValidationUx.state()")


def pseudo_content(page, selector, pseudo="::after"):
    return page.evaluate(
        "([s, p]) => getComputedStyle(document.querySelector(s), p).content", [selector, pseudo])


def computed(page, selector, prop):
    return page.evaluate(
        "([s, p]) => getComputedStyle(document.querySelector(s))[p]", [selector, prop])


def summary_li(page, key):
    return f'#model-smart-panel [data-summary-class="{key}"]'


@pytest.fixture(autouse=True)
def _no_js_errors_or_network(request):
    yield
    page = request.node.funcargs.get("page_under_test")
    if page is not None:
        assert page.js_errors == []
        assert not [u for u in page.network if u.startswith("http")]


@pytest.fixture
def page_under_test(make_page):
    return make_page(collapsed_sheets=("revenue",), panel=default_panel(
        runtime_state="CURRENT", assumption_register_view={"available": True, "entry_count": 1}))


# ═══════════════════════════════════════════════════════════════════════════
# Dense layout
# ═══════════════════════════════════════════════════════════════════════════

class TestDenseLayout:
    def test_editable_rows_are_single_line_and_compact(self, page_under_test):
        page = page_under_test
        metrics = page.evaluate("""() => [...document.querySelectorAll(
            '#panel-project-setup .v2-field-editable[data-fc-row]')].map(r => {
              const box = r.getBoundingClientRect();
              const label = r.querySelector('.v2-field-label').getBoundingClientRect();
              const input = r.querySelector('.v2-field-input').getBoundingClientRect();
              return {h: box.height, dy: Math.abs(label.top - input.top), w: input.width};
        })""")
        assert metrics, "no editable rows rendered"
        for m in metrics:
            assert m["h"] <= 40, m          # baseline on main was ~100px
            assert m["dy"] < 14, m          # label and control share one line
            assert m["w"] > 120, m

    def test_save_control_stays_available_but_leaves_the_flow(self, page_under_test):
        page = page_under_test
        page.focus(control(CAPACITY))
        page.wait_for_function(           # existing 0.1s opacity transition on :focus-within
            f"getComputedStyle(document.querySelector('{row(CAPACITY)} .v2-field-save')).opacity === '1'")
        box = page.evaluate(f"""() => {{
            const r = document.querySelector('{row(CAPACITY)}').getBoundingClientRect();
            const b = document.querySelector('{row(CAPACITY)} .v2-field-save').getBoundingClientRect();
            return {{rowH: r.height, inside: b.top >= r.top - 1 && b.bottom <= r.bottom + 1,
                    visible: getComputedStyle(document.querySelector('{row(CAPACITY)} .v2-field-save')).opacity}};
        }}""")
        assert box["inside"] and box["rowH"] <= 40 and box["visible"] == "1"
        assert page.get_attribute(f'{row(CAPACITY)} .v2-field-save', "aria-label") == "Save Installed Capacity"

    def test_no_horizontal_overflow_desktop_and_mobile(self, make_page):
        for width in (1440, 390):
            page = make_page(width=width, height=900)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), width

    def test_mobile_stacks_label_over_touch_sized_control(self, make_page):
        page = make_page(width=390, height=900)
        m = page.evaluate(f"""() => {{
            const label = document.querySelector('{row(CAPACITY)} .v2-field-label').getBoundingClientRect();
            const input = document.querySelector('{control(CAPACITY)}').getBoundingClientRect();
            return {{stacked: label.bottom <= input.top + 2, h: input.height}};
        }}""")
        assert m["stacked"] and m["h"] >= 36

    @pytest.mark.parametrize("tab,sheet", [("tab-revenue", "v2-sheet-revenue"),
                                           ("tab-debt", "v2-sheet-senior-debt")])
    def test_sticky_section_summary_never_covers_its_first_row(self, make_page, tab, sheet):
        """Regression: `overflow:hidden` on the card made it the summary's sticky
        scroll container, pushing the summary 77px down over the first fields."""
        page = make_page(collapsed_sheets=())
        page.click(f"#{tab}")
        page.evaluate("window.scrollTo(0, 0)")     # unscrolled: nothing is under the pinned summary
        geo = page.evaluate(f"""() => [...document.querySelectorAll('#{sheet} details.v2-inputs-section')].map(d => {{
            const s = d.querySelector(':scope > summary').getBoundingClientRect();
            const r = d.querySelector('.v2-field-row[data-fc-row]').getBoundingClientRect();
            return {{summaryBottom: s.bottom, rowTop: r.top, overflow: getComputedStyle(d).overflowY,
                    radius: getComputedStyle(d).borderTopLeftRadius}};
        }})""")
        assert geo
        for g in geo:
            assert g["summaryBottom"] <= g["rowTop"] + 1, g
            assert g["overflow"] == "clip" and g["radius"] == "8px", g

    def test_first_row_save_control_is_clickable_under_the_sticky_header(self, make_page):
        page = make_page(collapsed_sheets=())
        page.click("#tab-revenue")
        field_id = page.evaluate("document.querySelector('#v2-sheet-revenue .v2-field-editable').dataset.fieldId")
        page.locator(f'#panel-revenue [data-field-id="{field_id}"] input[name="value"]').fill("0.45")
        page.locator(f'#panel-revenue [data-field-id="{field_id}"] form button').first.click(timeout=4000)

    def test_read_only_rows_have_compact_non_stretched_badges(self, page_under_test):
        page = page_under_test
        badge = page.evaluate(f"""() => {{
            const b = document.querySelector('{row(LOCKED)} .v2-binding-badge').getBoundingClientRect();
            const r = document.querySelector('{row(LOCKED)}').getBoundingClientRect();
            return {{w: b.width, rowW: r.width}};
        }}""")
        assert badge["w"] < badge["rowW"] / 3          # was a full-width bar on main


# ═══════════════════════════════════════════════════════════════════════════
# pending / saving / error visuals
# ═══════════════════════════════════════════════════════════════════════════

class TestFieldStateVisuals:
    def test_pending_state_renders(self, page_under_test):
        page = page_under_test
        page.fill(control(CAPACITY), "12")
        assert "v2-field-pending" in page.get_attribute(row(CAPACITY), "class")
        assert computed(page, control(CAPACITY), "borderTopStyle") == "dashed"
        assert pseudo_content(page, row(CAPACITY)) == '"Unsaved"'

    def test_saving_state_renders(self, page_under_test):
        page = page_under_test
        page.fill(control(CAPACITY), "12")
        begin_save(page, CAPACITY)
        cls = page.get_attribute(row(CAPACITY), "class")
        assert "v2-field-saving" in cls and "v2-field-pending" not in cls
        assert page.get_attribute(row(CAPACITY), "aria-busy") == "true"
        assert pseudo_content(page, row(CAPACITY)) == '"Saving…"'
        assert "v2-field-saving-sweep" in computed(page, control(CAPACITY), "animationName")

    def test_error_state_renders(self, page_under_test):
        page = page_under_test
        type_and_submit(page, CAPACITY, "0")
        server_rejects(page, CAPACITY, "Installed Capacity must be ≥ 0.1 (got 0.0).")
        assert "v2-field-error" in page.get_attribute(row(CAPACITY), "class")
        assert pseudo_content(page, row(CAPACITY)) == '"Not saved"'
        assert computed(page, control(CAPACITY), "outlineStyle") == "solid"
        assert page.is_visible(f'{row(CAPACITY)} .v2-field-error-msg')

    def test_three_states_are_visually_distinct(self, page_under_test):
        page = page_under_test
        backgrounds = {}
        page.fill(control(CAPACITY), "12")
        backgrounds["pending"] = computed(page, row(CAPACITY), "backgroundColor")
        begin_save(page, CAPACITY)
        backgrounds["saving"] = computed(page, row(CAPACITY), "backgroundColor")
        server_rejects(page, CAPACITY)
        backgrounds["error"] = computed(page, row(CAPACITY), "backgroundColor")
        assert len(set(backgrounds.values())) == 3, backgrounds

    def test_reduced_motion_disables_the_saving_animation(self, page_under_test):
        page = page_under_test
        page.emulate_media(reduced_motion="reduce")
        page.fill(control(CAPACITY), "12")
        begin_save(page, CAPACITY)
        assert computed(page, control(CAPACITY), "animationName") == "none"

    def test_dark_scheme_uses_its_own_error_palette(self, page_under_test):
        page = page_under_test
        type_and_submit(page, CAPACITY, "0")
        server_rejects(page, CAPACITY)
        light = computed(page, row(CAPACITY), "backgroundColor")
        page.emulate_media(color_scheme="dark")
        assert computed(page, row(CAPACITY), "backgroundColor") != light


# ═══════════════════════════════════════════════════════════════════════════
# failed save
# ═══════════════════════════════════════════════════════════════════════════

class TestFailedSave:
    def test_failed_save_decorates_the_exact_row_and_keeps_the_entered_value(self, page_under_test):
        page = page_under_test
        type_and_submit(page, CAPACITY, "0")
        server_rejects(page, CAPACITY, "Installed Capacity must be ≥ 0.1 (got 0.0).")
        assert page.input_value(control(CAPACITY)) == "0"      # persisted value was blank
        assert page.get_attribute(control(CAPACITY), "data-pending") == "false"
        assert page.get_attribute(control(CAPACITY), "aria-invalid") == "true"
        assert page.get_attribute(row(CAPACITY), "data-error-class") == "OUT_OF_BOUNDS"
        msg = page.inner_text(f'{row(CAPACITY)} .v2-field-error-msg')
        assert msg.startswith("Out of bounds:") and "must be ≥ 0.1" in msg
        assert page.get_attribute(control(CAPACITY), "aria-describedby") == \
            page.get_attribute(f'{row(CAPACITY)} .v2-field-error-msg', "id")
        decorated = page.evaluate("[...document.querySelectorAll('.v2-field-error')]"
                                  ".map(r => r.dataset.fieldId)")
        assert decorated == [CAPACITY]

    @pytest.mark.parametrize("field_id,raw", [
        (NAME, ""), (NAME, "   "), (MONTHS, ""),
        (MONTHS, "0"), (MONTHS, "121"), (MONTHS, "1.5"),
        (CAPACITY, "0"), (CAPACITY, "-5"), (P50, "0.5"),
        ("project_setup.technical.horizon_years", "2.5"),
        ("project_setup.technical.horizon_years", "51"),
        (INDEX, "101"),
    ])
    def test_browser_class_matches_the_typed_server_classification(self, page_under_test, field_id, raw):
        from app.workbook.update_service import WorkbookUpdateService
        page = page_under_test
        SHEET_OF.setdefault(field_id, "project_setup")
        submitted = page.evaluate(
            """([fid, raw]) => {
                const input = document.querySelector('.v2-field-row[data-field-id="' + fid + '"] .v2-field-input');
                input.value = raw;
                return input.value;          // what the browser would actually submit
            }""", [field_id, raw])
        server_class = WorkbookUpdateService.validate_field_update(field_id, submitted).error_class
        assert server_class is not None, "probe must be a real server rejection"
        page.evaluate("""fid => {
            const input = document.querySelector('.v2-field-row[data-field-id="' + fid + '"] .v2-field-input');
            v2FieldValidationUx.noteSubmitted(fid, input.value);
            v2FieldValidationUx.register(fid, {message: 'whatever the server said'});
        }""", field_id)
        assert state(page)[0]["errorClass"] == server_class.value

    def test_untypeable_rejection_is_save_rejected_never_invalid(self, page_under_test):
        """stale != invalid: an in-bounds value refused for another reason stays unclassified."""
        page = page_under_test
        type_and_submit(page, CAPACITY, "50")
        server_rejects(page, CAPACITY,
                       "Draft changed since page loaded - values refreshed. Please try your edit again.")
        assert state(page)[0]["errorClass"] == "SAVE_REJECTED"
        assert page.is_visible(summary_li(page, "SAVE_REJECTED"))
        for key in ("INVALID", "OUT_OF_BOUNDS", "REQUIRED_MISSING"):
            assert not page.is_visible(summary_li(page, key))

    def test_classification_ignores_the_message_text(self, page_under_test):
        page = page_under_test
        type_and_submit(page, CAPACITY, "0")
        server_rejects(page, CAPACITY, "Required field is missing and the value is invalid!")
        assert state(page)[0]["errorClass"] == "OUT_OF_BOUNDS"      # from the min constraint only

    def test_error_survives_an_unrelated_sheet_re_render(self, page_under_test):
        page = page_under_test
        type_and_submit(page, CAPACITY, "0")
        server_rejects(page, CAPACITY, "Out of range.")
        type_and_submit(page, P50, "2750")
        server_accepts(page, P50)                       # re-renders the whole sheet
        assert "v2-field-error" in page.get_attribute(row(CAPACITY), "class")
        assert page.input_value(control(CAPACITY)) == "0"
        assert "v2-field-error" not in page.get_attribute(row(P50), "class")
        assert [e["fieldId"] for e in state(page)] == [CAPACITY]

    def test_successful_subsequent_save_clears_the_error(self, page_under_test):
        page = page_under_test
        type_and_submit(page, CAPACITY, "0")
        server_rejects(page, CAPACITY, "Out of range.")
        type_and_submit(page, CAPACITY, "50")
        server_accepts(page, CAPACITY)
        cls = page.get_attribute(row(CAPACITY), "class")
        assert "v2-field-error" not in cls
        assert page.query_selector(f'{row(CAPACITY)} .v2-field-error-msg') is None
        assert page.get_attribute(control(CAPACITY), "aria-invalid") is None
        assert state(page) == []
        assert page.is_visible('#model-smart-panel [data-summary-empty]')

    def test_a_save_of_another_field_does_not_clear_this_error(self, page_under_test):
        page = page_under_test
        type_and_submit(page, CAPACITY, "0")
        server_rejects(page, CAPACITY, "Out of range.")
        page.evaluate("document.dispatchEvent(new CustomEvent('workbook-field-saved',"
                      " {detail: {field_id: 'project_setup.technical.p50_hours', new_hash: 'h'}}))")
        assert [e["fieldId"] for e in state(page)] == [CAPACITY]

    def test_escape_reverts_to_the_persisted_value_and_clears_the_error(self, page_under_test):
        page = page_under_test
        type_and_submit(page, CAPACITY, "0")
        server_rejects(page, CAPACITY, "Out of range.")
        page.focus(control(CAPACITY))
        page.keyboard.press("Escape")
        assert page.input_value(control(CAPACITY)) == ""
        assert state(page) == []
        assert "v2-field-error" not in page.get_attribute(row(CAPACITY), "class")

    def test_re_editing_shows_pending_and_hides_the_stale_message(self, page_under_test):
        page = page_under_test
        type_and_submit(page, CAPACITY, "0")
        server_rejects(page, CAPACITY, "Out of range.")
        page.fill(control(CAPACITY), "5")
        cls = page.get_attribute(row(CAPACITY), "class")
        assert "v2-field-pending" in cls and "v2-field-error" not in cls
        assert not page.is_visible(f'{row(CAPACITY)} .v2-field-error-msg')

    def test_restored_failed_value_never_auto_resubmits_on_blur(self, page_under_test):
        page = page_under_test
        type_and_submit(page, CAPACITY, "0")
        server_rejects(page, CAPACITY, "Out of range.")
        page.evaluate("window.__requests = 0; document.addEventListener("
                      "'htmx:beforeRequest', () => window.__requests++)")
        page.focus(control(CAPACITY))
        page.evaluate(f"document.querySelector('{control(CAPACITY)}').blur()")
        assert page.evaluate("window.__requests") == 0

    def test_transport_failure_never_overwrites_the_server_message(self, page_under_test):
        page = page_under_test
        type_and_submit(page, CAPACITY, "0")
        server_rejects(page, CAPACITY, "Server said this.")
        page.evaluate("""fid => v2FieldValidationUx.registerIfAbsent(fid, {message: 'generic network text'})""",
                      CAPACITY)
        assert state(page)[0]["message"] == "Server said this."

    def test_transport_failure_without_a_server_message_is_save_rejected(self, page_under_test):
        page = page_under_test
        type_and_submit(page, CAPACITY, "50")
        page.evaluate(f"""() => {{
            const form = document.querySelector('{row(CAPACITY)} form');
            document.dispatchEvent(new CustomEvent('htmx:afterRequest',
                {{detail: {{elt: form, successful: false, xhr: {{responseURL: '/v2/workbook/update'}}}}}}));
        }}""")
        entry = state(page)[0]
        assert entry["errorClass"] == "SAVE_REJECTED" and "could not be completed" in entry["message"]

    def test_only_editable_rows_can_ever_be_decorated(self, page_under_test, make_page):
        page = page_under_test
        assert page.evaluate("fid => v2FieldValidationUx.register(fid, {message: 'x'})", LOCKED) is False
        assert state(page) == []
        protected = make_page(project_editable=False)
        assert protected.evaluate("fid => v2FieldValidationUx.register(fid, {message: 'x'})", CAPACITY) is False
        assert protected.query_selector("form, .v2-field-input") is None
        assert protected.query_selector(".v2-field-error") is None


# ═══════════════════════════════════════════════════════════════════════════
# Smart Panel validation summary
# ═══════════════════════════════════════════════════════════════════════════

class TestSummary:
    def _register_all(self, page):
        type_and_submit(page, NAME, "")
        server_rejects(page, NAME, "Project Name is required.")
        type_and_submit(page, MONTHS, "1.5")
        server_rejects(page, MONTHS, "must be a whole number")
        type_and_submit(page, CAPACITY, "0")
        server_rejects(page, CAPACITY, "must be ≥ 0.1")
        type_and_submit(page, P50, "5000")
        server_rejects(page, P50, "Draft changed since page loaded.")

    def test_summary_shows_each_error_class_separately_with_the_right_fields(self, page_under_test):
        page = page_under_test
        self._register_all(page)
        expected = {"REQUIRED_MISSING": NAME, "INVALID": MONTHS,
                    "OUT_OF_BOUNDS": CAPACITY, "SAVE_REJECTED": P50}
        for key, field_id in expected.items():
            assert page.is_visible(summary_li(page, key)), key
            assert page.inner_text(f'{summary_li(page, key)} [data-summary-count]') == "1"
            jumps = page.eval_on_selector_all(
                f'{summary_li(page, key)} [data-jump-field]',
                "els => els.map(e => e.getAttribute('data-jump-field'))")
            assert jumps == [field_id], key
        assert not page.is_visible('#model-smart-panel [data-summary-empty]')

    def test_summary_entries_name_the_sheet_and_the_field_label(self, page_under_test):
        page = page_under_test
        type_and_submit(page, CAPACITY, "0")
        server_rejects(page, CAPACITY, "must be ≥ 0.1")
        item = page.inner_text(f'{summary_li(page, "OUT_OF_BOUNDS")} [data-summary-fields] li')
        assert "Installed Capacity" in item and "Project Setup" in item and "must be ≥ 0.1" in item

    def test_summary_clears_with_the_error(self, page_under_test):
        page = page_under_test
        self._register_all(page)
        for field_id in (NAME, MONTHS, CAPACITY, P50):
            server_accepts(page, field_id)
        for key in ("REQUIRED_MISSING", "INVALID", "OUT_OF_BOUNDS", "SAVE_REJECTED"):
            assert not page.is_visible(summary_li(page, key))
        assert page.is_visible('#model-smart-panel [data-summary-empty]')

    def test_summary_is_repopulated_after_the_panel_is_replaced_out_of_band(self, page_under_test):
        from model_workspace_harness import render_panel
        page = page_under_test
        type_and_submit(page, CAPACITY, "0")
        server_rejects(page, CAPACITY, "must be ≥ 0.1")
        page.evaluate("""html => {
            document.getElementById('model-smart-panel').outerHTML = html;
            document.dispatchEvent(new CustomEvent('htmx:oobAfterSwap', {detail: {}}));
        }""", render_panel(default_panel(assumption_register_view={"available": True, "entry_count": 1})))
        assert page.is_visible(summary_li(page, "OUT_OF_BOUNDS"))
        assert page.inner_text(f'{summary_li(page, "OUT_OF_BOUNDS")} [data-summary-count]') == "1"

    def test_stale_last_run_is_shown_apart_from_input_errors(self, make_page):
        page = make_page(panel=default_panel(
            runtime_state="STALE", assumption_register_view={"available": True, "entry_count": 1}))
        assert page.is_visible(summary_li(page, "STALE_LAST_RUN"))
        assert page.inner_text(f'{summary_li(page, "STALE_LAST_RUN")} .v2-smart-panel-row-value') == "STALE"
        for key in ("REQUIRED_MISSING", "INVALID", "OUT_OF_BOUNDS", "SAVE_REJECTED"):
            assert not page.is_visible(summary_li(page, key))
        assert page.is_visible('#model-smart-panel [data-summary-empty]')

    def test_unavailable_authority_is_not_a_field_error(self, make_page):
        page = make_page(panel=default_panel(
            trust_pack={"last_run": {"state": "UNAVAILABLE"}},
            assumption_register_view={"available": False, "entry_count": 0}))
        assert page.is_visible(summary_li(page, "AUTHORITY_UNAVAILABLE"))
        assert state(page) == []
        for key in ("REQUIRED_MISSING", "INVALID", "OUT_OF_BOUNDS", "SAVE_REJECTED"):
            assert not page.is_visible(summary_li(page, key))

    def test_read_only_count_matches_the_rendered_rows(self, page_under_test, make_page):
        page = page_under_test
        expected = page.evaluate("document.querySelectorAll('.v2-field-readonly[data-fc-row]').length")
        assert expected > 0
        assert page.inner_text(f'{summary_li(page, "NON_EDITABLE")} [data-summary-count]') == str(expected)
        protected = make_page(project_editable=False)
        total = protected.evaluate("document.querySelectorAll('.v2-field-row[data-fc-row]').length")
        assert protected.inner_text(f'{summary_li(protected, "NON_EDITABLE")} [data-summary-count]') == str(total)


# ═══════════════════════════════════════════════════════════════════════════
# jump-to-field
# ═══════════════════════════════════════════════════════════════════════════

class TestJumpToField:
    def _fail(self, page, field_id, raw, message="out of range"):
        type_and_submit(page, field_id, raw)
        page.evaluate(
            """([fid, message]) => document.dispatchEvent(new CustomEvent(
                'workbook-field-error', {detail: {field_id: fid, message: message}}))""",
            [field_id, message])

    def test_jump_reaches_the_exact_semantic_field_across_tab_and_collapsed_group(self, page_under_test):
        page = page_under_test
        assert page.evaluate("document.getElementById('panel-revenue').hidden") is True
        assert page.evaluate("document.querySelector('#v2-sheet-revenue details').open") is False
        self._fail(page, INDEX, "101")
        page.click(f'{summary_li(page, "OUT_OF_BOUNDS")} [data-jump-field="{INDEX}"]')
        info = page.evaluate("""() => {
            const el = document.activeElement;
            const r = el.closest('.v2-field-row').getBoundingClientRect();
            return {field: el.closest('.v2-field-row').dataset.fieldId,
                    isControl: el.classList.contains('v2-field-input'),
                    selected: document.getElementById('tab-revenue').getAttribute('aria-selected'),
                    panelHidden: document.getElementById('panel-revenue').hidden,
                    detailsOpen: el.closest('details').open,
                    visible: !!el.offsetParent,
                    inViewport: r.top >= 0 && r.bottom <= window.innerHeight,
                    highlighted: el.closest('.v2-field-row').classList.contains('v2-field-jump-highlight'),
                    activeCell: window.FcActiveCellManager.getActiveCell().cell.addr};
        }""")
        assert info == {"field": INDEX, "isControl": True, "selected": "true", "panelHidden": False,
                        "detailsOpen": True, "visible": True, "inViewport": True, "highlighted": True,
                        "activeCell": f"revenue.{INDEX}.value"}

    def test_collapsed_group_and_tab_are_open_before_focus_lands(self, page_under_test):
        page = page_under_test
        page.evaluate("""() => {
            window.__focusLog = [];
            document.addEventListener('focusin', e => {
                const d = e.target.closest('details'); const p = e.target.closest('.v2-sheet-panel');
                window.__focusLog.push({field: (e.target.closest('.v2-field-row') || {dataset: {}}).dataset.fieldId,
                    detailsOpen: d ? d.open : null, panelHidden: p ? p.hidden : null,
                    visible: !!e.target.offsetParent});
            });
        }""")
        assert page.evaluate("fid => v2JumpToField(fid)", INDEX) is True
        landing = [e for e in page.evaluate("window.__focusLog") if e["field"] == INDEX]
        assert landing and all(e["detailsOpen"] is True and e["panelHidden"] is False and e["visible"]
                               for e in landing)

    def test_every_nested_collapsed_ancestor_is_opened(self, page_under_test):
        page = page_under_test
        page.evaluate("""() => {
            const inner = document.querySelector('#v2-sheet-revenue details');
            const outer = document.createElement('details');
            outer.id = 'outer-group'; inner.parentNode.insertBefore(outer, inner); outer.appendChild(inner);
        }""")
        assert page.evaluate("document.getElementById('outer-group').open") is False
        page.evaluate("fid => v2JumpToField(fid)", INDEX)
        assert page.evaluate("document.getElementById('outer-group').open") is True
        assert page.evaluate("document.querySelector('#v2-sheet-revenue details').open") is True

    def test_highlight_is_short_and_transient(self, page_under_test):
        page = page_under_test
        page.evaluate("fid => v2JumpToField(fid)", CAPACITY)
        assert "v2-field-jump-highlight" in page.get_attribute(row(CAPACITY), "class")
        page.wait_for_function(
            f"!document.querySelector('{row(CAPACITY)}').classList.contains('v2-field-jump-highlight')",
            timeout=4000)

    @pytest.mark.parametrize("key", ["Enter", "Space"])
    def test_jump_buttons_are_keyboard_operable(self, page_under_test, key):
        page = page_under_test
        self._fail(page, INDEX, "101")
        page.focus(f'{summary_li(page, "OUT_OF_BOUNDS")} [data-jump-field="{INDEX}"]')
        page.keyboard.press(key)
        assert page.evaluate("document.activeElement.closest('.v2-field-row').dataset.fieldId") == INDEX
        assert page.evaluate("document.activeElement.classList.contains('v2-field-input')") is True

    def test_jump_to_a_read_only_row_focuses_its_value_and_stays_read_only(self, page_under_test):
        page = page_under_test
        assert page.evaluate("fid => v2JumpToField(fid)", LOCKED) is True
        info = page.evaluate("""() => ({
            field: document.activeElement.closest('.v2-field-row').dataset.fieldId,
            isValue: document.activeElement.classList.contains('v2-field-value'),
            controls: document.activeElement.closest('.v2-field-row')
                .querySelectorAll('input, select, textarea, form').length,
            editable: document.activeElement.closest('.v2-field-row').classList.contains('v2-field-editable')})""")
        assert info == {"field": LOCKED, "isValue": True, "controls": 0, "editable": False}

    def test_jump_to_an_unknown_field_is_a_no_op(self, page_under_test):
        page = page_under_test
        before = page.evaluate("document.querySelector('#v2-sheet-tabs [aria-selected=true]').id")
        assert page.evaluate("v2JumpToField('does.not.exist')") is False
        assert page.evaluate("document.querySelector('#v2-sheet-tabs [aria-selected=true]').id") == before

    def test_jump_never_changes_values_editability_or_runs_a_request(self, page_under_test):
        page = page_under_test
        snapshot = ("[...document.querySelectorAll('.v2-field-input')]"
                    ".map(i => i.name + '=' + i.value).join('|')")
        before = page.evaluate(snapshot)
        editable_before = page.evaluate("document.querySelectorAll('.v2-field-editable').length")
        page.evaluate("window.__req = 0; document.addEventListener('htmx:beforeRequest', () => window.__req++)")
        for field_id in (INDEX, CAPACITY, LOCKED):
            page.evaluate("fid => v2JumpToField(fid)", field_id)
        assert page.evaluate(snapshot) == before
        assert page.evaluate("document.querySelectorAll('.v2-field-editable').length") == editable_before
        assert page.evaluate("window.__req") == 0
        assert page.network == []
