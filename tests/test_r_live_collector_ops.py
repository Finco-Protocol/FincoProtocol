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
    assert service["TimeoutStartSec"] == "540"
    readme = (OPS / "README.md").read_text(encoding="utf-8")
    assert "exit **75**" in readme
    assert "Batch exit **0**" in readme and "Exit **1**" in readme
    assert "acquisition exception" in readme and "history initialization" in readme
    assert "persistence or close failure" in readme


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


def test_staging_collector_is_isolated_and_all_approved():
    staging = OPS / "staging"
    config = ConfigParser(interpolation=None)
    assert config.read(staging / "finco-staging-r-live-collector.service", encoding="utf-8")
    service = config["Service"]
    timer = ConfigParser(interpolation=None)
    assert timer.read(staging / "finco-staging-r-live-collector.timer", encoding="utf-8")
    start = service["ExecStart"]
    assert service["WorkingDirectory"] == "/opt/finco_staging"
    assert service["EnvironmentFile"] == "/opt/finco_staging/.env.r-live-collector"
    assert "python -m app.radar_rwa.r_live_collect" in start
    assert "--asset-key" not in start
    assert "/opt/finco_protocol" not in start and "/var/lib/finco/" not in start
    assert service["ReadWritePaths"] == "/opt/finco_staging/storage"
    assert not config.has_section("Install")
    assert timer["Timer"]["Unit"] == "finco-staging-r-live-collector.service"
    assert timer["Timer"]["OnCalendar"] == "*-*-* *:00/5:00"
    env = (staging / "r-live-collector.staging.env.example").read_text(encoding="utf-8")
    assert "ROBINHOOD_RPC_URL=\n" in env
    assert "RADAR_BNB_INTELLIGENCE_DB_PATH=/opt/finco_staging/storage/radar_bnb_intelligence.db" in env
    assert "0600" in env


def test_web_and_collector_staging_templates_share_history_contract():
    root = OPS.parents[1]
    web = (root / "deploy" / "staging.env.example").read_text(encoding="utf-8")
    collector = (OPS / "staging" / "r-live-collector.staging.env.example").read_text(encoding="utf-8")
    path = "RADAR_BNB_INTELLIGENCE_DB_PATH=/opt/finco_staging/storage/radar_bnb_intelligence.db"
    assert path in web and path in collector
    assert "ROBINHOOD_RPC_URL=\n" in web and "ROBINHOOD_RPC_URL=\n" in collector
    assert "same" in web.lower() and "same" in collector.lower()
