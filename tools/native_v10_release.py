"""Offline release step for the V10 native kernels (deploy time only - never during a Run).

    python -m tools.native_v10_release install   build both kernels into a temporary directory with the reviewed build
                                                 scripts, require every identity field of the produced manifests to
                                                 equal the committed reviewed manifests (artifact SHA-256, build ID, ABI,
                                                 source SHA-256, sealed approved-blob manifest, compiler, flags, target,
                                                 variant), install only the two shared objects atomically, then verify
                                                 them through the production loaders
    python -m tools.native_v10_release verify    verify the installed kernels through the production loaders
    python -m tools.native_v10_release remove    delete the installed kernels (every Run is then canonical Python)

Exit status 0 only when the verified kernels are installed (``install`` / ``verify``) or absent (``remove``). On any
mismatch nothing is installed and previously installed kernels are removed, so a failed release can never leave an
unverified binary behind. The committed manifests are never rewritten.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "financial_engine" / "native_v10"
KERNELS = (("financial_engine.native_v10.build", "fk_v10_manifest.json"),
           ("financial_engine.native_v10.build_stage2", "fk_v10_stage2_manifest.json"))
IDENTITY = ("abi_version", "approved_blobs_sha256", "artifact", "artifact_sha256", "build_id", "compiler", "flags",
            "source_sha256", "target", "variant", "stage")


def _artifacts() -> list[Path]:
    return [NATIVE / json.loads((NATIVE / manifest).read_text())["artifact"] for _module, manifest in KERNELS]


def remove() -> int:
    for path in _artifacts():
        path.unlink(missing_ok=True)
    print("native_v10 release: kernels removed; Runs are served by canonical Python")
    return 0


def verify() -> dict:
    """Load both kernels in a FRESH interpreter through the production loaders; raise on any refusal."""
    code = ("import json; from financial_engine.native_v10 import eligibility, loader, stage2\n"
            "s1 = loader.get_native(); s2 = stage2.get_stage2()\n"
            "print(json.dumps({'runtime': eligibility.check_runtime(), 'stage1': s1[1] or s1[0].build_id,"
            " 'stage2': s2[1] or s2[0][1], 'ok': s1[0] is not None and s2[0] is not None}))")
    proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    if proc.returncode:
        raise RuntimeError(f"loader verification failed: {proc.stderr.strip()[-400:]}")
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    if not result["ok"]:
        raise RuntimeError(f"production loaders refused the kernels: {result}")
    return result


def _build(module: str, out: Path) -> None:
    subprocess.run([sys.executable, "-m", module, "--out", str(out)], cwd=ROOT, check=True,
                   capture_output=True, text=True, timeout=600)


def install() -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="native_v10_release_") as tmp:
            out = Path(tmp)
            for module, manifest_name in KERNELS:
                _build(module, out)
                built = json.loads((out / manifest_name).read_text())
                reviewed = json.loads((NATIVE / manifest_name).read_text())
                diff = sorted(k for k in IDENTITY if built.get(k) != reviewed.get(k))
                if diff:
                    raise RuntimeError(f"{manifest_name}: built kernel differs from the reviewed manifest in {diff}")
            for _module, manifest_name in KERNELS:
                name = json.loads((NATIVE / manifest_name).read_text())["artifact"]
                staged = NATIVE / f".{name}.staged"
                staged.write_bytes((out / name).read_bytes())
                os.chmod(staged, 0o644)
                os.replace(staged, NATIVE / name)                  # atomic per file
        result = verify()
    except Exception as exc:  # noqa: BLE001 - fail closed: never leave an unverified binary installed
        for path in _artifacts():
            path.unlink(missing_ok=True)
        for staged in NATIVE.glob(".*.staged"):
            staged.unlink(missing_ok=True)
        print(f"native_v10 release: REFUSED ({exc}); no kernel installed, Runs stay canonical", file=sys.stderr)
        return 1
    print(f"native_v10 release: installed and verified {json.dumps(result, sort_keys=True)}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("install", "verify", "remove"))
    action = parser.parse_args(argv).action
    if action == "install":
        return install()
    if action == "remove":
        return remove()
    try:
        print(f"native_v10 release: verified {json.dumps(verify(), sort_keys=True)}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"native_v10 release: NOT VERIFIED ({exc})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
