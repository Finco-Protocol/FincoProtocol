"""Operator readiness of native Run activation (FINCO43B). Server-side CLI only - nothing is exposed over HTTP.

    python -m tools.native_status            # JSON; exit 0 = consistent (OFF or ENABLED and loadable), 1 = action needed

Reports, from the SAME environment the web service reads (run it with the service's environment, e.g. through
``systemd-run --property=EnvironmentFile=...`` or after sourcing .env/.env.native):

* ``v10`` / ``v11``: the effective per-Run setting exactly as ``app.runtime.native_activation`` decides it for a NEW Run
  (``off`` + reason ``SETTING_OFF`` | ``INVALID_SETTING`` | ``KILL_SWITCH`` | ``KILL_SWITCH_UNREADABLE``, or the mode),
  and any build-ID pin;
* ``kernels``: each production loader's verdict (None = loadable) and the loaded build ID vs the committed manifest;
* ``release_profile``: which reviewed activation profile the activation file is exactly (or None);
* ``status``: OFF | KILLED | ENABLED | ENABLED_LOADER_UNAVAILABLE | ENABLED_BUILD_PIN_MISMATCH | INVALID_CONFIG.

No secrets, tenant data or input values are read or printed. Loading a kernel here is the same read-only check the
release verification performs; it does not start a Run.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def status(environ=None) -> dict:
    from app.runtime import native_activation as na
    from tools import native_release as rel

    env = os.environ if environ is None else environ
    v10_mode, v10_reason = na.setting(env)
    v11_mode, v11_reason = na.v11_setting(env)
    pins = {"v10": (env.get(na.ENV_BUILD_ID) or "").strip() or None,
            "v11": (env.get(na.ENV_V11_BUILD_ID) or "").strip() or None}
    committed = {"stage1": rel._manifest(*rel.KERNELS[0][::2])["build_id"],
                 "stage2": rel._manifest(*rel.KERNELS[1][::2])["build_id"],
                 "stage3": rel._manifest(*rel.KERNELS[2][::2])["build_id"]}
    kernels = {}
    try:
        from financial_engine.native_v10 import loader, stage2
        from financial_engine.native_v11 import stage3

        for name, (lib, why) in (("stage1", loader.get_native()), ("stage2", stage2.get_stage2()),
                                 ("stage3", stage3.get_stage3())):
            build = None if lib is None else (lib[1] if isinstance(lib, tuple) else getattr(lib, "build_id", None))
            kernels[name] = {"loader_reason": why, "build_id": build, "committed_build_id": committed[name],
                             "matches_committed": build == committed[name]}
    except Exception as exc:  # noqa: BLE001 - reported, never hidden
        kernels["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"

    needed = []
    if v10_mode != "off":
        needed += ["stage1"] + (["stage2"] if v10_mode == "stage1+2" else [])
    if v11_mode != "off":
        needed.append("stage3")
    reasons = {v10_reason, v11_reason}
    if "INVALID_SETTING" in reasons:
        state = "INVALID_CONFIG"
    elif not needed:
        state = "KILLED" if reasons & {"KILL_SWITCH", "KILL_SWITCH_UNREADABLE"} else "OFF"
    elif "error" in kernels or any(kernels[k]["loader_reason"] for k in needed):
        state = "ENABLED_LOADER_UNAVAILABLE"
    elif (pins["v10"] and v10_mode != "off" and pins["v10"] != kernels["stage1"]["build_id"]) or (
            pins["v11"] and v11_mode != "off" and pins["v11"] != kernels["stage3"]["build_id"]):
        state = "ENABLED_BUILD_PIN_MISMATCH"
    else:
        state = "ENABLED"
    return {"status": state,
            "v10": {"mode": v10_mode, "reason": v10_reason, "build_id_pin": pins["v10"]},
            "v11": {"mode": v11_mode, "reason": v11_reason, "build_id_pin": pins["v11"]},
            "needed_kernels": needed, "kernels": kernels, "release_profile": rel.installed_profile()}


def main(argv=None) -> int:
    out = status()
    print(json.dumps(out, indent=1, sort_keys=True))
    return 0 if out["status"] in ("OFF", "KILLED", "ENABLED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
