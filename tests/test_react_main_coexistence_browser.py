"""Integrated real-server preview acceptance; no production flag changes."""
from tests.test_workflow_c_browser_v1 import browser, live_server


def test_nonmodel_preview_four_widths_keeps_canonical_urls(live_server, browser, monkeypatch):
    monkeypatch.setenv('FINCO_NONMODEL_PREVIEW', '1')
    page=browser.new_page()
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    try:
        for width in (1440,900,390,320):
            page.set_viewport_size({'width':width,'height':900})
            response=page.goto(live_server+'/v2/non-model')
            assert response.status==200
            page.wait_for_selector('[data-surface="non-model"]')
            page.wait_for_timeout(250)
            assert page.evaluate('document.documentElement.scrollWidth-document.documentElement.clientWidth')<=1
            assert not page.locator('script[src*="finco-react.js"]').count()
        assert not errors,errors
    finally:
        page.close()
