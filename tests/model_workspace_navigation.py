"""Browser test adapter for the real Option C controls (not hidden compatibility buttons)."""


def activate_destination(page, tab_id):
    destination = page.evaluate("""id => {
      const manifest = JSON.parse(document.getElementById('workspace-destinations').textContent);
      let d = manifest.destinations.find(d => d.tab_id === id);
      if (d && d.alias_of) d = manifest.destinations.find(item => item.tab_id === d.alias_of);
      return d;
    }""", tab_id)
    assert destination, tab_id
    target = destination['tab_id']
    if destination['area'] != 'overview':
        page.locator(f'[data-hy-group="{destination["area"]}"]').click()
    if page.get_attribute(f'#{target}', 'aria-selected') != 'true':
        drawer = page.locator('[data-workspace-drawer][aria-controls="model-workspace-nav"]')
        if drawer.is_visible() and drawer.get_attribute('aria-expanded') != 'true':
            drawer.click()
        page.locator(f'#model-workspace-nav [data-nav-tab="{target}"]').click()
    if target == 'tab-overview' and page.get_attribute('#tab-overview', 'aria-selected') != 'true':
        page.locator('#model-workspace-nav [data-nav-tab="tab-overview"]').click()


def open_insight(page):
    button = page.locator('[data-workspace-drawer][aria-controls="model-smart-panel"]')
    if button.get_attribute('aria-expanded') != 'true':
        button.click()
