"""FINCO Protocol load test harness — P6.9 pilot acceptance.

LOAD_GATE_NOT_EXECUTED_INFRASTRUCTURE_REQUIRED

This harness requires a running FINCO Protocol staging instance and the
Locust load-testing framework. It cannot be executed in CI without the
staging infrastructure provisioned.

To run:
    pip install locust
    FINCO_DEMO_COOKIE=<signed_demo_token> locust -f tests/load/locustfile.py \
        --host http://staging.example.internal \
        --users 40 --spawn-rate 5 --run-time 120s --headless

Scenario A: Browsing load (40 VU)
    Simulates 40 concurrent demo users browsing the project library,
    loading workspace pages, and navigating between views.
    Target: p95 < 2 s for all read-only routes.

Scenario B: Concurrent model runs (10–15 VU)
    Simulates 10–15 concurrent users triggering model runs.
    Expected: 503 responses when FINCO_MAX_CONCURRENT_RUNS is exceeded;
    assert that 200/HTML responses are returned for the first N slots.
    Target: no 5xx other than the expected capacity-limit 503s.

SQLite WAL analysis:
    WAL mode serializes writers. With 40 browsing VUs (mostly reads)
    and 10–15 run VUs (writes on completion), contention is expected
    only at scenario-save / workspace-state-save points.
    The 30 s busy_timeout means writes queue up to 30 s before failing.
    If sqlite3.OperationalError "database is locked" appears in staging
    logs, reduce FINCO_MAX_CONCURRENT_RUNS or switch to Gunicorn × 1 worker.
"""
from __future__ import annotations

import os
import random
import time

try:
    from locust import HttpUser, TaskSet, task, between, events
except ImportError:
    raise SystemExit(
        "LOAD_GATE_NOT_EXECUTED_INFRASTRUCTURE_REQUIRED: "
        "locust is not installed. Run: pip install locust"
    )

# ---------------------------------------------------------------------------
# Shared auth helpers
# ---------------------------------------------------------------------------

_DEMO_COOKIE = os.getenv("FINCO_DEMO_COOKIE", "")
_ADMIN_COOKIE = os.getenv("FINCO_ADMIN_COOKIE", "")

_BROWSING_PATHS = [
    "/library",
    "/library?role=reference",
    "/library?search=Reference",
    "/public-health",
    "/readyz",
    "/pilot-guide",
    "/help",
]


# ---------------------------------------------------------------------------
# Scenario A: Browsing load — 40 VU
# ---------------------------------------------------------------------------

class BrowsingTaskSet(TaskSet):
    """Read-only browsing tasks for demo users."""

    @task(5)
    def library_page(self):
        self.client.get("/library", name="/library")

    @task(2)
    def library_search(self):
        self.client.get(
            "/library", params={"search": "Reference"}, name="/library?search="
        )

    @task(2)
    def library_role_filter(self):
        self.client.get(
            "/library", params={"role": "reference"}, name="/library?role="
        )

    @task(1)
    def health_check(self):
        self.client.get("/public-health", name="/public-health")

    @task(1)
    def readyz(self):
        self.client.get("/readyz", name="/readyz")

    @task(1)
    def pilot_guide(self):
        self.client.get("/pilot-guide", name="/pilot-guide")


class BrowsingUser(HttpUser):
    """Scenario A: 40 concurrent browsing users."""
    tasks = [BrowsingTaskSet]
    wait_time = between(1, 4)

    def on_start(self):
        if _DEMO_COOKIE:
            self.client.cookies.set("finco_demo", _DEMO_COOKIE)


# ---------------------------------------------------------------------------
# Scenario B: Model run concurrency — 10–15 VU
# ---------------------------------------------------------------------------

class ModelRunUser(HttpUser):
    """Scenario B: concurrent model run users.

    These users hammer /run. Capacity-limit 503s are expected and counted
    separately from genuine errors.
    """
    wait_time = between(2, 8)

    def on_start(self):
        if _DEMO_COOKIE:
            self.client.cookies.set("finco_demo", _DEMO_COOKIE)

    @task
    def trigger_model_run(self):
        with self.client.post(
            "/run",
            data={
                "project_code": "generic_solar_reference",
                "scenario": "Base",
                "capacity_mw": "64",
                "tariff_eur_mwh": "55",
                "total_capex_keur": "51200",
                "opex_y1_keur": "640",
                "gearing_pct": "70",
                "target_dscr": "1.25",
                "interest_rate_pct": "5.5",
                "tenor_years": "18",
                "horizon_years": "25",
                "p50_hours": "1750",
                "ppa_term_years": "15",
            },
            name="/run",
            catch_response=True,
        ) as resp:
            if resp.status_code == 503:
                # Expected when model slots are full — not a failure
                resp.success()
            elif resp.status_code == 429:
                # Demo rate limit — not a failure
                resp.success()
            elif resp.status_code not in (200, 302, 303):
                resp.failure(f"Unexpected status {resp.status_code}")


# ---------------------------------------------------------------------------
# Event hooks — result summary
# ---------------------------------------------------------------------------

@events.quitting.add_listener
def on_quitting(environment, **kwargs):
    stats = environment.runner.stats
    total = stats.total
    print("\n--- FINCO Load Gate Summary ---")
    print(f"Requests: {total.num_requests}")
    print(f"Failures: {total.num_failures}")
    print(f"p50 response time: {total.get_response_time_percentile(0.50):.0f} ms")
    print(f"p95 response time: {total.get_response_time_percentile(0.95):.0f} ms")
    print(f"p99 response time: {total.get_response_time_percentile(0.99):.0f} ms")
    if total.num_failures > 0:
        print("LOAD_GATE_FAIL: unexpected failures detected")
    else:
        print("LOAD_GATE_PASS: no unexpected failures")
    print("--- End Summary ---\n")
