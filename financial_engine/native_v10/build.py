"""Offline build of the V10 Stage 1 candidate kernel (research). NEVER invoked at runtime.

Produces ``_fk_v10.so`` and ``fk_v10_manifest.json`` next to this file. The build ID is the SHA256 of
(kernel source, exact flags, compiler identification, ABI version, target triple), injected into the
binary and re-verified by the loader together with the shared object's own SHA256.

usage: python -m financial_engine.native_v10.build [--out DIR] [--variant release|asan|alloc]
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
SOURCE = HERE / "kernel_v10.c"
ABI_VERSION = 10001
BASE_FLAGS = ["-std=c11", "-O2", "-fno-fast-math", "-ffp-contract=off", "-fno-strict-aliasing",
              "-fPIC", "-shared", "-fstack-protector-strong", "-D_FORTIFY_SOURCE=2",
              "-fvisibility=default", "-Wall", "-Wextra", "-Werror=implicit-function-declaration"]
REPRO_FLAGS = ["-ffile-prefix-map={src}=.", "-Wl,--build-id=none", "-Wl,--hash-style=gnu"]
VARIANTS = {
    "release": [],
    "asan": ["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"],
    "alloc": ["-DFK_TEST_ALLOC"],
}


def compiler_id(cc: str) -> str:
    out = subprocess.run([cc, "--version"], capture_output=True, text=True, check=True).stdout
    return out.splitlines()[0].strip()


def build(out_dir: Path, variant: str = "release", cc: str = "gcc") -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    src_bytes = SOURCE.read_bytes()
    flags = BASE_FLAGS + [f.format(src=str(HERE)) for f in REPRO_FLAGS] + VARIANTS[variant]
    target = subprocess.run([cc, "-dumpmachine"], capture_output=True, text=True, check=True).stdout.strip()
    # Build identity is checkout-path independent (G3): it hashes the flag TEMPLATE, not the expanded
    # absolute source path. -ffile-prefix-map keeps the object code path independent as well.
    ident = {
        "abi_version": ABI_VERSION, "source_sha256": hashlib.sha256(src_bytes).hexdigest(),
        "flags": BASE_FLAGS + REPRO_FLAGS + VARIANTS[variant], "compiler": compiler_id(cc), "target": target,
        "variant": variant,
    }
    build_id = hashlib.sha256(json.dumps(ident, sort_keys=True).encode()).hexdigest()
    so_name = "_fk_v10.so" if variant == "release" else f"_fk_v10_{variant}.so"
    so_path = out_dir / so_name
    # build from a fixed relative path so the output does not depend on the checkout location
    cmd = [cc, *flags, f'-DFK_BUILD_ID="{build_id}"', "-o", str(so_path), "kernel_v10.c", "-lm"]
    subprocess.run(cmd, cwd=HERE, check=True)
    so_sha = hashlib.sha256(so_path.read_bytes()).hexdigest()
    manifest = {**ident, "build_id": build_id, "artifact": so_name, "artifact_sha256": so_sha,
                "built_with_python": platform.python_version(),
                # immutable-provenance seal: the approved canonical-source manifest this artifact is released with
                "approved_blobs_sha256": hashlib.sha256((HERE / "approved_canonical_blobs.json").read_bytes()).hexdigest(),
                "command": [c.replace(str(HERE), "<native_v10>").replace(str(out_dir), "<out>") for c in cmd]}
    (out_dir / f"fk_v10_manifest{'' if variant == 'release' else '_' + variant}.json").write_text(
        json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
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
