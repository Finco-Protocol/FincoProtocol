"""Network-free deployment-contract checks; no timer or collector is started."""
from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path


OPS = Path(__file__).resolve().parents[1] / "deploy" / "r_live_collector_v1"


def unit(name: str) -> ConfigParser:
    config = ConfigParser(interpolation=None)
    assert config.read(OPS / name, encoding="utf-8")
    return config


def test_one_shot_collector_is_only_scheduled_writer():
    service = unit("finco-r-live-collector.service")
    timer = unit("finco-r-live-collector.timer")
    start = service["Service"]["ExecStart"]
    assert service["Service"]["Type"] == "oneshot"
    assert "python -m app.radar_rwa.r_live_collect" in start
    assert timer["Timer"]["Unit"] == "finco-r-live-collector.service"
    assert not service.has_section("Install")  # no accidental independent enable
    assert "ExecStart" not in timer["Timer"]
    assert "finco-web" not in start


def test_default_five_minute_cadence_is_unrandomized_and_external():
    timer = unit("finco-r-live-collector.timer")["Timer"]
    assert timer["OnCalendar"] == "*-*-* *:00/5:00"
    assert timer["AccuracySec"] == "1s"
    assert timer["RandomizedDelaySec"] == "0"
    assert timer["Persistent"] == "true"
    readme = (OPS / "README.md").read_text(encoding="utf-8")
    assert "T+60m to T+65m" in readme
    assert "2-minute" in readme and "Do not silently change" in readme
    assert "web-process loop" in readme


def test_os_lock_nonoverlap_and_failure_semantics():
    service = unit("finco-r-live-collector.service")["Service"]
    assert service["ExecStart"].startswith(
        "/usr/bin/flock -n -E 75 /var/lib/finco/radar/r-live-collector.lock ")
    assert service["StateDirectory"] == "finco/radar"
    assert service["Restart"] == "no"
    assert service["TimeoutStartSec"] == "240"
    readme = (OPS / "README.md").read_text(encoding="utf-8")
    assert "exit **75**" in readme
    assert "Exit **0**" in readme and "exit **1**" in readme
    assert "missing or" in readme and "history persistence" in readme


def test_durable_shared_history_and_secret_safe_configuration():
    service = unit("finco-r-live-collector.service")["Service"]
    example = (OPS / "r-live-collector.env.example").read_text(encoding="utf-8")
    readme = (OPS / "README.md").read_text(encoding="utf-8")
    assert service["User"] == service["Group"] == "finco"
    assert service["WorkingDirectory"] == "/opt/finco_protocol"
    assert service["EnvironmentFile"] == "/etc/finco/r-live-collector.env"
    assert service["UMask"] == "0077"
    assert "ROBINHOOD_RPC_URL=\n" in example  # never commit a real endpoint
    assert "RADAR_BNB_INTELLIGENCE_DB_PATH=/var/lib/finco/radar/radar_bnb_intelligence.db" in example
    assert "same" in readme.lower() and "B1.3 ledger" in readme
    assert "online backup" in readme and "never delete, truncate" in readme
    assert "0600" in readme
    assert "StandardOutput" in service and service["StandardOutput"] == "journal"
    assert "StandardError" in service and service["StandardError"] == "journal"
    assert "NoNewPrivileges" in service and service["NoNewPrivileges"] == "true"
    assert "Do not install or enable" in readme


def test_install_update_remove_and_health_instructions_present():
    readme = (OPS / "README.md").read_text(encoding="utf-8")
    for instruction in (
        "systemd-analyze verify", "systemd-analyze calendar",
        "systemctl daemon-reload", "systemctl start finco-r-live-collector.service",
        "systemctl enable --now finco-r-live-collector.timer",
        "systemctl list-timers", "journalctl -u finco-r-live-collector.service",
        "systemctl disable --now finco-r-live-collector.timer",
    ):
        assert instruction in readme
