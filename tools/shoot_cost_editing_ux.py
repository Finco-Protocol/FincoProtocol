#!/usr/bin/env python3
"""Screenshot evidence for the CAPEX/OPEX editing UX (synthetic data, local Chromium).

    python tools/shoot_cost_editing_ux.py --out docs/model_v2/evidence/cost_ux_v2/before
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--chromium", default=os.environ.get("FINCO_TEST_CHROMIUM_PATH", "/opt/pw-browsers/chromium"))
    args = ap.parse_args()
    logging.disable(logging.CRITICAL)
    import bench_cost_editing_ux as B
    from playwright.sync_api import sync_playwright

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    server, thread = B.start_server(tempfile.mkdtemp(prefix="cost-shots-"))
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"], executable_path=args.chromium)
        for label, viewport, scheme in (("desktop-light", {"width": 1440, "height": 900}, "light"),
                                        ("desktop-dark", {"width": 1440, "height": 900}, "dark"),
                                        ("mobile-390-light", {"width": 390, "height": 844}, "light"),
                                        ("mobile-390-dark", {"width": 390, "height": 844}, "dark")):
            b = B.Bench(browser, "solar", viewport=viewport)
            b.page.emulate_media(color_scheme=scheme)
            b.open()
            b.tab("capex")
            b.page.evaluate("window.scrollTo(0,0)")
            b.page.screenshot(path=str(out / f"capex-initial-{label}.png"))
            for i, v in enumerate((1111, 2222, 3333)):         # three real edits, committed with Enter
                b.type_amount("capex", i, v)
                b.page.keyboard.press("Enter")
            b.page.wait_for_timeout(700)
            first = b.page.locator("#v2-sheet-capex form[data-cost-row]").first
            first.scroll_into_view_if_needed()
            b.page.screenshot(path=str(out / f"capex-three-edits-{label}.png"))
            b.close()
        browser.close()
    server.should_exit = True
    thread.join(timeout=10)
    print("wrote", sorted(p.name for p in out.glob("*.png")))


if __name__ == "__main__":
    main()
