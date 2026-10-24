"""Production release transaction for the native Run kernels: V10 Stage 1 + Stage 2 and V11 Stage 3 (deploy time only -
never during a Run).

    python -m tools.native_release install   1. build all three kernels into a temporary directory with the reviewed
                                                build scripts and require every identity field of each produced manifest
                                                to equal the committed reviewed manifest (artifact SHA-256, build ID, ABI,
                                                source SHA-256, sealed approved-blob manifest, compiler, flags, target,
                                                variant);
                                             2. install only the three shared objects, atomically per file;
                                             3. verify them in a FRESH interpreter through the production loaders
                                                (runtime, ABI, build-ID pins, source authentication) and run an exact
                                                replay self-test: the same Model Run canonical, with V10 Stage 1+2
                                                alone and with the combined V10 Stage 1+2 + V11 Stage 3 production
                                                configuration must be byte-identical and really served natively;
                                             4. require that the installed ``finco-web`` unit loads ``ACTIVATION_FILE``;
                                             5. atomically write ``ACTIVATION_FILE`` (``.env.native``: the permanent
                                                production activation with both build-ID pins; no secrets, never the
                                                operator's ``.env``).
                                             Exit 0 only when every step passed. On any failure nothing stays installed
                                             (kernels and activation file removed): every Run is canonical Python.
    python -m tools.native_release verify    steps 3 + 4 for the installed kernels and the activation file
    python -m tools.native_release remove    delete the kernels and the activation file (canonical after a restart;
                                             for an immediate rollback without restart use the kill-switch files)

The committed manifests are never rewritten. Nothing here compiles at runtime or touches the web server process.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "financial_engine"
# (package directory, build module, committed manifest)
KERNELS = ((ENGINE / "native_v10", "financial_engine.native_v10.build", "fk_v10_manifest.json"),
           (ENGINE / "native_v10", "financial_engine.native_v10.build_stage2", "fk_v10_stage2_manifest.json"),
           (ENGINE / "native_v11", "financial_engine.native_v11.build_stage3", "fk_v11_stage3_manifest.json"))
IDENTITY = ("abi_version", "approved_blobs_sha256", "artifact", "artifact_sha256", "build_id", "compiler", "flags",
            "source_sha256", "target", "variant", "stage")
ACTIVATION_FILE = ROOT / ".env.native"
UNIT = "finco-web.service"
SELF_TEST = ("Solar", "Base")


def _manifest(directory: Path, name: str) -> dict:
    return json.loads((directory / name).read_text(encoding="utf-8"))


def _artifacts() -> list[Path]:
    return [directory / _manifest(directory, name)["artifact"] for directory, _module, name in KERNELS]


def activation_text() -> str:
    """The exact production activation: V10 Stage 1+2 and V11 Stage 3, each pinned to its reviewed build ID."""
    s1 = _manifest(*KERNELS[0][::2])["build_id"]
    s3 = _manifest(*KERNELS[2][::2])["build_id"]
    return ("# Written by tools/native_release.py install after the kernels were built, verified and self-tested.\n"
            "# Do not edit; remove with: deploy/scripts/release_native.sh remove. No secrets in this file.\n"
            "FINCO_NATIVE_V10_RUN=stage1+2\n"
            f"FINCO_NATIVE_V10_RUN_BUILD_ID={s1}\n"
            "FINCO_NATIVE_V11_RUN=on\n"
            f"FINCO_NATIVE_V11_RUN_BUILD_ID={s3}\n")


def remove() -> int:
    for path in (*_artifacts(), ACTIVATION_FILE):
        path.unlink(missing_ok=True)
    print("native release: kernels and activation removed; after the next restart every Run is canonical Python")
    return 0


_VERIFY = r"""
import hashlib, json, pickle, sys
from financial_engine.native_v10 import eligibility, loader, stage2
from financial_engine.native_v10.config import NativeConfig, native_run
from financial_engine.native_v11 import stage3
from financial_engine.native_v11.config import Stage3Config, stage3_run
s1_id, s3_id, project, scenario = sys.argv[1:5]
s1 = loader.get_native(); s2 = stage2.get_stage2(); s3 = stage3.get_stage3()
out = {"runtime": eligibility.check_runtime(), "stage1": s1[1] or s1[0].build_id, "stage2": s2[1] or s2[0][1],
       "stage3": s3[1] or s3[0].build_id}
out["loaders_ok"] = s1[0] is not None and s2[0] is not None and s3[0] is not None
if out["loaders_ok"]:
    from app.api.project_runner import run_project
    from app.services import production_financial_authority as pfa
    def run():
        pfa._POLICY_RUN_CACHE.clear()
        return hashlib.sha256(pickle.dumps(run_project(project, scenario), protocol=5)).hexdigest()
    canonical = run()
    v10 = NativeConfig(mode="candidate", stage2_experimental=True, require_build_id=s1_id)
    with native_run(v10) as alone:                       # V10 Stage 1+2 alone
        v10_only = run()
    with native_run(v10) as st10, stage3_run(Stage3Config(mode="candidate", require_build_id=s3_id)) as st3:
        combined = run()                                 # the production configuration: Stage 3 on top of V10 1+2
    out["self_test"] = {"run": [project, scenario], "digest": canonical,
                        "identical": v10_only == canonical and combined == canonical,
                        "v10_alone_native_calls": alone.native_solves + alone.stage2_native_calls,
                        "v10_build_id": alone.build_id, "v11_native_models": st3.native_models,
                        "v11_build_id": st3.build_id, "v11_declines": dict(st3.declines),
                        "combined_v10_native_calls": st10.native_solves + st10.stage2_native_calls}
print(json.dumps(out, sort_keys=True))
"""


def verify() -> dict:
    """Production loaders + exact replay self-test in a FRESH interpreter; raise on any refusal."""
    s1_id = _manifest(*KERNELS[0][::2])["build_id"]
    s3_id = _manifest(*KERNELS[2][::2])["build_id"]
    proc = subprocess.run([sys.executable, "-c", _VERIFY, s1_id, s3_id, *SELF_TEST], cwd=ROOT, capture_output=True,
                          text=True, timeout=600)
    if proc.returncode:
        raise RuntimeError(f"loader verification failed: {proc.stderr.strip()[-400:]}")
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    if not result["loaders_ok"]:
        raise RuntimeError(f"production loaders refused the kernels: {result}")
    test = result["self_test"]
    if not (test["identical"] and test["v10_alone_native_calls"] > 0 and test["v11_native_models"] > 0
            and test["v10_build_id"] == s1_id and test["v11_build_id"] == s3_id):
        raise RuntimeError(f"exact replay self-test failed: {test}")
    return result


def unit_loads_activation() -> str | None:
    """``None`` when the installed ``finco-web`` unit loads ``ACTIVATION_FILE``, else the reason."""
    systemctl = shutil.which("systemctl")
    if systemctl is None:
        return "systemctl is unavailable: cannot prove the service loads the activation file"
    proc = subprocess.run([systemctl, "show", UNIT, "-p", "EnvironmentFiles", "--value"], capture_output=True,
                          text=True, timeout=30)
    if proc.returncode or str(ACTIVATION_FILE) not in proc.stdout:
        return (f"the installed {UNIT} does not load {ACTIVATION_FILE}; install deploy/systemd/{UNIT} "
                "and run systemctl daemon-reload first")
    return None


def _write_activation() -> None:
    staged = ACTIVATION_FILE.with_name(f".{ACTIVATION_FILE.name}.staged")
    staged.write_text(activation_text(), encoding="utf-8")
    os.chmod(staged, 0o644)
    os.replace(staged, ACTIVATION_FILE)


def _build(module: str, out: Path) -> None:
    subprocess.run([sys.executable, "-m", module, "--out", str(out)], cwd=ROOT, check=True,
                   capture_output=True, text=True, timeout=600)


def _cleanup() -> None:
    for path in (*_artifacts(), ACTIVATION_FILE):
        path.unlink(missing_ok=True)
    for directory in {d for d, _m, _n in KERNELS} | {ACTIVATION_FILE.parent}:
        for staged in directory.glob(".*.staged"):
            staged.unlink(missing_ok=True)


def install() -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="native_release_") as tmp:
            out = Path(tmp)
            for directory, module, name in KERNELS:
                _build(module, out)
                built, reviewed = _manifest(out, name), _manifest(directory, name)
                diff = sorted(k for k in IDENTITY if built.get(k) != reviewed.get(k))
                if diff:
                    raise RuntimeError(f"{name}: built kernel differs from the reviewed manifest in {diff}")
            for directory, _module, name in KERNELS:
                artifact = _manifest(directory, name)["artifact"]
                staged = directory / f".{artifact}.staged"
                staged.write_bytes((out / artifact).read_bytes())
                os.chmod(staged, 0o644)
                os.replace(staged, directory / artifact)          # atomic per file
        result = verify()
        reason = unit_loads_activation()
        if reason:
            raise RuntimeError(reason)
        _write_activation()
    except Exception as exc:  # noqa: BLE001 - fail closed: never leave an unverified or unreachable activation
        _cleanup()
        print(f"native release: REFUSED ({exc}); no kernel and no activation installed, Runs stay canonical",
              file=sys.stderr)
        return 1
    print(f"native release: installed, verified and activated {json.dumps(result, sort_keys=True)}; "
          f"restart {UNIT} to serve Runs natively")
    return 0


def check() -> int:
    try:
        result = verify()
        reason = unit_loads_activation()
        if reason:
            raise RuntimeError(reason)
        if not ACTIVATION_FILE.is_file() or ACTIVATION_FILE.read_text(encoding="utf-8") != activation_text():
            raise RuntimeError(f"{ACTIVATION_FILE} is missing or differs from the reviewed activation")
    except Exception as exc:  # noqa: BLE001
        print(f"native release: NOT VERIFIED ({exc})", file=sys.stderr)
        return 1
    print(f"native release: verified and activated {json.dumps(result, sort_keys=True)}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("install", "verify", "remove"))
    action = parser.parse_args(argv).action
    return {"install": install, "verify": check, "remove": remove}[action]()


if __name__ == "__main__":
    raise SystemExit(main())
