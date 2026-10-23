"""Offline build of the Stage 2 EXPERIMENTAL SHL kernel (research). NEVER invoked at runtime.

Separate artifact (``_fk_v10_stage2.so`` + ``fk_v10_stage2_manifest.json``) so the Stage 1 binary and
its sanitizer/fuzz evidence are unchanged. Same flags, same reproducibility rules as ``build.py``.

usage: python -m financial_engine.native_v10.build_stage2 [--out DIR] [--variant release|asan]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path

from .build import BASE_FLAGS, REPRO_FLAGS, VARIANTS, compiler_id

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "kernel_v10_stage2.c"
ABI_VERSION = 20001


def build(out_dir: Path, variant: str = "release", cc: str = "gcc") -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    flags = BASE_FLAGS + [f.format(src=str(HERE)) for f in REPRO_FLAGS] + VARIANTS[variant]
    target = subprocess.run([cc, "-dumpmachine"], capture_output=True, text=True, check=True).stdout.strip()
    ident = {"abi_version": ABI_VERSION, "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
             "flags": BASE_FLAGS + REPRO_FLAGS + VARIANTS[variant], "compiler": compiler_id(cc), "target": target,
             "variant": variant,
             "stage": "STAGE2_EXPERIMENTAL"}
    build_id = hashlib.sha256(json.dumps(ident, sort_keys=True).encode()).hexdigest()
    so_name = "_fk_v10_stage2.so" if variant == "release" else f"_fk_v10_stage2_{variant}.so"
    cmd = [cc, *flags, f'-DFK_BUILD_ID="{build_id}"', "-o", str(out_dir / so_name), SOURCE.name, "-lm"]
    subprocess.run(cmd, cwd=HERE, check=True)
    manifest = {**ident, "build_id": build_id, "artifact": so_name,
                "artifact_sha256": hashlib.sha256((out_dir / so_name).read_bytes()).hexdigest(),
                "built_with_python": platform.python_version(),
                # immutable-provenance seal: the approved canonical-source manifest this artifact is released with
                "approved_blobs_sha256": hashlib.sha256((HERE / "approved_canonical_blobs_stage2.json").read_bytes()).hexdigest(),
                "command": [c.replace(str(HERE), "<native_v10>").replace(str(out_dir), "<out>") for c in cmd]}
    (out_dir / f"fk_v10_stage2_manifest{'' if variant == 'release' else '_' + variant}.json").write_text(
        json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE))
    ap.add_argument("--variant", default="release", choices=sorted(VARIANTS))
    ap.add_argument("--cc", default=os.environ.get("CC", "gcc"))
    args = ap.parse_args(argv)
    print(json.dumps(build(Path(args.out), args.variant, args.cc), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
