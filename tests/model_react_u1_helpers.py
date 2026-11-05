"""PR-U1 helpers shared by the browser acceptance bodies: the cost lines live in the CAPEX / OPEX workbench and "+ Add line" is an inline row."""


# Literal UX-PR1 contract; no production route data is imported into this oracle.
NAV_LABELS = ("Overview", "Inputs", "Project", "Technical", "CAPEX", "OPEX", "Revenue", "Financing", "Tax",
              "Statements", "Results", "Debt metrics", "Scenarios", "Analysis", "Model checks", "Trust")


def ensure_navigation_open(page):
    nav = page.locator('[data-workspace-nav]')
    if not nav.is_visible():
        page.locator('.wsv2-menu').click()
    nav.wait_for(state='visible')
    return nav


def navigation_link(page, label):
    return ensure_navigation_open(page).locator('a', has_text=label).first


def input_jump(page, label):
    """Use the one primary navigation; import remains in the explicit shortcuts disclosure."""
    destinations = {'Project setup':'inputs/project', 'Assumptions':'inputs/technical', 'CAPEX':'inputs/capex',
                    'OPEX':'inputs/opex', 'Revenue & PPA':'inputs/revenue', 'Financing':'financing'}
    if label == 'Import':
        ensure_navigation_open(page).locator('[data-workspace-destination="inputs"]').click()
        details = page.locator('.ux-input-tools')
        if details.get_attribute('open') is None:
            details.locator('summary').click()
        details.locator('[data-jump-label="Import"]').click()
    else:
        ensure_navigation_open(page).locator(f'[data-workspace-destination="{destinations[label]}"]').click()


def open_cost_help(page):
    details = page.locator('[data-cost-grid]:visible .ux-grid-help')
    details.wait_for(state='visible')
    if details.get_attribute('open') is None:
        details.locator('summary').click()


def open_workbench(page, sheet="capex"):
    """Opens the workbench of ``sheet`` through the Inputs group links (history entry, no reload) and returns its grid."""
    grid = page.locator(f"[data-cost-grid='{sheet}']")
    if not grid.is_visible():
        input_jump(page, sheet.upper())
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
