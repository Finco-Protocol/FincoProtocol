"""PR-U1 helpers shared by the browser acceptance bodies: the cost lines live in the CAPEX / OPEX workbench and "+ Add line" is an inline row."""


def open_workbench(page, sheet="capex"):
    """Opens the workbench of ``sheet`` through the Inputs group links (history entry, no reload) and returns its grid."""
    grid = page.locator(f"[data-cost-grid='{sheet}']")
    if not grid.is_visible():
        page.locator(f"[data-inputs-jump] [data-jump-label='{sheet.upper()}']").click()
    grid.wait_for(state="visible", timeout=60000)
    page.wait_for_selector(f"[data-cost-grid='{sheet}'] [data-group-saved-total]", timeout=60000)
    return grid


def open_inline_add(page, sheet="capex", group=None):
    """Opens the inline add-line form (under ``group`` or the first group) and returns it."""
    grid = open_workbench(page, sheet)
    (grid.locator(f"[data-cost-group-add='{group}']") if group else grid.locator("[data-cost-addline]")).click()
    form = page.locator(f"[data-cost-line-manager='{sheet}']")
    form.wait_for(state="visible", timeout=30000)
    return form


def line_row(page, sheet, label):
    """The grid row of the line whose description is ``label``."""
    return page.locator(f"[data-cost-grid='{sheet}'] tr[data-line]", has=page.locator(f"input[aria-label='Label for {label}']"))


def row_action(page, row, action):
    """``action`` is 'Deactivate line' or 'Reactivate line': the real row-menu command (deactivation still asks to confirm)."""
    row.locator("[data-row-menu]").click()
    row.get_by_role("menuitem", name=action).click()
