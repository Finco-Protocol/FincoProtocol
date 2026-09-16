"""R6 live proof: typed in-process composition plus safe JSON/HTML artifacts."""
from __future__ import annotations

import json
import os
from pathlib import Path

from finco_radar.r3.live_proof import CANDIDATE_SYMBOLS
from finco_radar.terminal.presenter import reconstruct_terminal_digest
from finco_radar.terminal.runtime import build_live_terminal_snapshot
from finco_radar.terminal.web import render_terminal_html


def run(symbols=CANDIDATE_SYMBOLS) -> tuple[dict, str]:
    snapshot = build_live_terminal_snapshot(symbols)
    if reconstruct_terminal_digest(snapshot) != snapshot.terminal_snapshot_digest:
        raise RuntimeError("terminal digest reconstruction failed")
    return snapshot.to_evidence_dict(), render_terminal_html(snapshot)


def main() -> int:
    configured = os.getenv("RADAR_R6_SYMBOLS")
    symbols = tuple(x.strip().upper() for x in configured.split(",") if x.strip()) if configured else CANDIDATE_SYMBOLS
    evidence_path = Path(os.getenv("RADAR_R6_EVIDENCE_PATH", "artifacts/radar_r6_terminal_evidence.json"))
    html_path = Path(os.getenv("RADAR_R6_HTML_PATH", "artifacts/radar_r6_terminal.html"))
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        evidence, rendered = run(symbols)
        evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
        html_path.write_text(rendered, encoding="utf-8")
        print(json.dumps({"status": evidence["status"], "evidence": str(evidence_path),
                          "html": str(html_path)}, sort_keys=True))
        return 0
    except Exception as exc:
        failure = {"status": "INFRASTRUCTURE_ERROR", "detail": f"{type(exc).__name__}:{exc}"}
        evidence_path.write_text(json.dumps(failure, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(failure, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
