"""Runtime V2 — real first/second POST /v2/workbook/run measurement.

Boots the real app (lifespan included, so startup prewarm runs), then times:
  first  POST /v2/workbook/run   — first user Run after application startup
  second POST /v2/workbook/run   — immediate re-run (same inputs, memo hit path)

Usage:
    python tools/bench_first_request.py [--no-prewarm]

--no-prewarm disables the startup prewarm hook (monkeypatched) to show the
cost the first request WOULD pay without Runtime V2 Workstream A.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.persistence import db  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-prewarm", action="store_true")
    args = parser.parse_args()

    tmp = tempfile.mkdtemp(prefix="finco-first-request-")
    db.DB_PATH = os.path.join(tmp, "first-request.db")
    db.init_db()

    if args.no_prewarm:
        # disable the startup prewarm hook to measure the lazy baseline
        import main_web  # noqa: F401
        for handler in main_web.app.router.on_startup:
            if handler.__name__ == "_prewarm_model_workers":
                main_web.app.router.on_startup.remove(handler)
                break

    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project
    from fastapi.testclient import TestClient
    import main_web

    record = create_reference_seeded_project(
        user_id="perf-first-request",
        template_source="generic_solar_reference",
        requested_name="First Request Benchmark",
        capacity_mw=64.0,
    )
    cookies = {COOKIE_NAME: create_session_token(user_id="perf-first-request",
                                                 username="admin")}

    t0 = time.perf_counter()
    client = TestClient(main_web.app)  # lifespan runs the startup prewarm
    with client:
        startup_s = time.perf_counter() - t0

        page = client.get(f"/v2/workbook?project={record.project_code}",
                          cookies=cookies)
        assert page.status_code == 200, page.status_code
        h = re.search(r'name="content_hash" value="([^"]+)"', page.text).group(1)
        v = re.search(r'name="workbook_version" value="([^"]+)"', page.text).group(1)

        t1 = time.perf_counter()
        r1 = client.post("/v2/workbook/run",
                         data={"project": record.project_code,
                               "content_hash": h, "workbook_version": v},
                         cookies=cookies, headers={"HX-Request": "true"})
        first_s = time.perf_counter() - t1
        assert r1.status_code == 200

        page = client.get(f"/v2/workbook?project={record.project_code}",
                          cookies=cookies)
        h = re.search(r'name="content_hash" value="([^"]+)"', page.text).group(1)
        t2 = time.perf_counter()
        r2 = client.post("/v2/workbook/run",
                         data={"project": record.project_code,
                               "content_hash": h, "workbook_version": v},
                         cookies=cookies, headers={"HX-Request": "true"})
        second_s = time.perf_counter() - t2
        assert r2.status_code == 200

    mode = "WITHOUT prewarm" if args.no_prewarm else "WITH prewarm"
    print(f"[{mode}]")
    print(f"  startup (incl. prewarm when on): {startup_s:.2f}s")
    print(f"  first  POST /v2/workbook/run:    {first_s:.2f}s")
    print(f"  second POST /v2/workbook/run:    {second_s:.2f}s")


if __name__ == "__main__":
    main()
