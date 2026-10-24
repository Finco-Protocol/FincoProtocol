"""Offline build of the V11 Stage 3 candidate kernel. NEVER invoked at runtime.

Produces ``_fk_v11_stage3.so`` and ``fk_v11_stage3_manifest.json`` next to this file (or in --out).
The build ID is the SHA256 of (kernel source, exact flags, compiler identification, ABI version,
target triple, variant), injected into the binary and re-verified by the loader together with the
shared object's own SHA256 and the sealed approved canonical-source manifest
(``approved_canonical_blobs_stage3.json``). The V10 Stage 1/Stage 2 build scripts, artifacts and
manifests are separate and untouched.

usage: python -m financial_engine.native_v11.build_stage3 [--out DIR] [--variant release|asan|alloc]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "kernel_v11_stage3.c"
APPROVED = HERE / "approved_canonical_blobs_stage3.json"
ABI_VERSION = 30001
BASE_FLAGS = ["-std=c11", "-O2", "-fno-fast-math", "-ffp-contract=off", "-fno-strict-aliasing",
              "-fPIC", "-shared", "-fstack-protector-strong", "-D_FORTIFY_SOURCE=2",
              "-fvisibility=default", "-Wall", "-Wextra", "-Werror=implicit-function-declaration"]
REPRO_FLAGS = ["-ffile-prefix-map={src}=.", "-Wl,--build-id=none", "-Wl,--hash-style=gnu"]
VARIANTS = {
    "release": [],
    "asan": ["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"],
    "alloc": ["-DFK_TEST_ALLOC"],
}
ARTIFACT = "_fk_v11_stage3.so"
MANIFEST = "fk_v11_stage3_manifest.json"


def compiler_id(cc: str) -> str:
    out = subprocess.run([cc, "--version"], capture_output=True, text=True, check=True).stdout
    return out.splitlines()[0].strip()


def build(out_dir: Path, variant: str = "release", cc: str = "gcc") -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    src_bytes = SOURCE.read_bytes()
    flags = BASE_FLAGS + [f.format(src=str(HERE)) for f in REPRO_FLAGS] + VARIANTS[variant]
    target = subprocess.run([cc, "-dumpmachine"], capture_output=True, text=True, check=True).stdout.strip()
    ident = {
        "abi_version": ABI_VERSION, "source_sha256": hashlib.sha256(src_bytes).hexdigest(),
        "flags": BASE_FLAGS + REPRO_FLAGS + VARIANTS[variant], "compiler": compiler_id(cc), "target": target,
        "variant": variant,
    }
    build_id = hashlib.sha256(json.dumps(ident, sort_keys=True).encode()).hexdigest()
    so_name = ARTIFACT if variant == "release" else f"_fk_v11_stage3_{variant}.so"
    so_path = out_dir / so_name
    cmd = [cc, *flags, f'-DFK_BUILD_ID="{build_id}"', "-o", str(so_path), SOURCE.name, "-lm"]
    subprocess.run(cmd, cwd=HERE, check=True)
    so_sha = hashlib.sha256(so_path.read_bytes()).hexdigest()
    manifest = {**ident, "build_id": build_id, "artifact": so_name, "artifact_sha256": so_sha,
                "built_with_python": platform.python_version(),
                "approved_blobs_sha256": hashlib.sha256(APPROVED.read_bytes()).hexdigest(),
                "command": [c.replace(str(HERE), "<native_v11>").replace(str(out_dir), "<out>") for c in cmd]}
    name = MANIFEST if variant == "release" else f"fk_v11_stage3_manifest_{variant}.json"
    (out_dir / name).write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE))
    ap.add_argument("--variant", default="release", choices=sorted(VARIANTS))
    ap.add_argument("--cc", default=os.environ.get("CC", "gcc"))
    args = ap.parse_args(argv)
    if shutil.which(args.cc) is None:
        print(f"compiler {args.cc!r} not found", file=sys.stderr)
        return 2
    print(json.dumps(build(Path(args.out), args.variant, args.cc), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
