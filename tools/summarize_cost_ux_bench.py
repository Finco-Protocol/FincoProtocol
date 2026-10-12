#!/usr/bin/env python3
"""Markdown before/after table from two bench_cost_editing_ux.py JSON files (medians across verticals)."""
from __future__ import annotations

import json
import statistics
import sys

SCENARIOS = [("capex_1", "One CAPEX cell"), ("opex_1", "One OPEX cell"), ("opex_4", "Four consecutive OPEX cells"),
             ("mixed_10", "Ten mixed CAPEX/OPEX cells")]


def med(data, scenario, mode, metric):
    vals = [v[f"{scenario}:{mode}"][metric]["median"] for v in data["scenarios"].values() if f"{scenario}:{mode}" in v]
    return statistics.median(vals) if vals else float("nan")


def ranged(data, scenario, mode, metric):
    vals = [v[f"{scenario}:{mode}"][metric]["median"] for v in data["scenarios"].values() if f"{scenario}:{mode}" in v]
    return f"{min(vals):.0f}–{max(vals):.0f}" if vals else "n/a"


def main(before_path, after_path):
    before, after = (json.load(open(p, encoding="utf-8")) for p in (before_path, after_path))
    print("| Scenario | Mode | First key → confirmed (ms, median; range over 4 verticals) | Last action → confirmed (ms) | Requests | POST | Server TTFB total (ms) | DOM settle total (ms) | Response KB |")
    print("|---|---|---|---|---|---|---|---|---|")
    for key, title in SCENARIOS:
        for mode in ("immediate", "staged"):
            row = [title, mode,
                   f"{med(after, key, mode, 'ms'):.0f} ({ranged(after, key, mode, 'ms')})",
                   f"{med(after, key, mode, 'confirm_ms'):.0f}",
                   f"{med(after, key, mode, 'requests'):.0f}", f"{med(after, key, mode, 'posts'):.0f}",
                   f"{med(after, key, mode, 'server_ttfb_ms'):.0f}", f"{med(after, key, mode, 'dom_settle_ms'):.0f}",
                   f"{med(after, key, mode, 'bytes') / 1024:.0f}"]
            print("| " + " | ".join(row) + " |")
    print()
    print("Default experience, before (immediate per-row autosave) vs after (batch save):")
    print()
    print("| Scenario | Before: ms | Before: requests (POST) | After: ms | After: requests (POST) | Time saved | Requests saved |")
    print("|---|---|---|---|---|---|---|")
    for key, title in SCENARIOS:
        b_ms, b_rq, b_po = med(before, key, "immediate", "ms"), med(before, key, "immediate", "requests"), med(before, key, "immediate", "posts")
        a_ms, a_rq, a_po = med(after, key, "staged", "ms"), med(after, key, "staged", "requests"), med(after, key, "staged", "posts")
        print(f"| {title} | {b_ms:.0f} | {b_rq:.0f} ({b_po:.0f}) | {a_ms:.0f} | {a_rq:.0f} ({a_po:.0f}) | "
              f"{(1 - a_ms / b_ms) * 100:.0f}% | {b_rq - a_rq:.0f} |")
    print()
    print("Stale-authority probe (immediate OPEX save, then staged CAPEX Save):")
    for label, data in (("before", before), ("after", after)):
        res = {v: d.get("probe_staged_save_after_opex_save", {}).get("saved") for v, d in data["scenarios"].items()}
        print(f"- {label}: " + ", ".join(f"{v}={'saved' if ok else 'FALSE 409'}" for v, ok in res.items()))
    print()
    print("Focus kept in the grid after the action (share of repetitions, median across verticals):")
    for label, data in (("before", before), ("after", after)):
        for key, title in SCENARIOS:
            vals = [v[f"{key}:staged"]["focus_kept_in_grid_ratio"] for v in data["scenarios"].values() if f"{key}:staged" in v]
            print(f"- {label} / {title} (staged): {statistics.median(vals):.2f}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
