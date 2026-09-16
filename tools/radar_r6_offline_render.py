"""Render a deterministic R6 fixture without network access."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from finco_radar.terminal.presenter import reconstruct_terminal_digest
from finco_radar.terminal.web import render_terminal_html


def main() -> int:
    test_path = REPOSITORY_ROOT / "tests" / "test_radar_r6_terminal.py"
    spec = importlib.util.spec_from_file_location("radar_r6_fixtures", test_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load deterministic R6 fixture factories")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    snapshot, _ = module.terminal(buy=("-75", "-80"), sell=("0", "0"))
    if reconstruct_terminal_digest(snapshot) != snapshot.terminal_snapshot_digest:
        raise RuntimeError("offline terminal digest reconstruction failed")
    output = Path("artifacts/radar_r6_offline_terminal.html")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_terminal_html(snapshot), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
