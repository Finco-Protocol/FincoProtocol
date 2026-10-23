"""Gap G3: the native build is checkout-path independent and reproduces the approved binaries.

The kernel sources, build scripts and sealed approved-source manifests are copied into two unrelated
absolute paths of different depth and built there with the repository's own build scripts. Both builds
must produce byte-identical shared objects and identical manifests (except the informational
``built_with_python``). With the approved toolchain, they must equal the committed manifests, i.e. the
binary sha256 the loader verifies. A different toolchain is reported as a skip, never as a pass."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

from tests.native_v10_support import ARTIFACTS, HERE, approved_fields, committed_manifest, compiler_or_skip

FILES = ("__init__.py", "build.py", "build_stage2.py", "kernel_v10.c", "kernel_v10_stage2.c",
         "approved_canonical_blobs.json", "approved_canonical_blobs_stage2.json")


def _build_copy(root):
    pkg = root / "financial_engine" / "native_v10"
    pkg.mkdir(parents=True)
    (root / "financial_engine" / "__init__.py").write_text("")
    for name in FILES:
        shutil.copy(HERE / name, pkg / name)
    out = root / "out"
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = str(root)
    for module in ("financial_engine.native_v10.build", "financial_engine.native_v10.build_stage2"):
        proc = subprocess.run([sys.executable, "-m", module, "--out", str(out)], cwd=str(root), env=env,
                              capture_output=True, text=True, timeout=300)
        assert proc.returncode == 0, proc.stderr[-2000:]
    return out


def test_build_is_path_independent_and_reproduces_the_approved_artifacts(tmp_path):
    compiler = compiler_or_skip()
    a = _build_copy(tmp_path / "a")
    b = _build_copy(tmp_path / "b" / "a" / "much" / "deeper" / "checkout")
    for manifest_name, so in ARTIFACTS.items():
        assert (a / so).read_bytes() == (b / so).read_bytes(), so
        ma = json.loads((a / manifest_name).read_text())
        mb = json.loads((b / manifest_name).read_text())
        assert approved_fields(ma) == approved_fields(mb)
        expected = committed_manifest(manifest_name)
        if ma["compiler"] != expected["compiler"]:
            pytest.skip(f"toolchain {compiler!r} is not the approved build toolchain {expected['compiler']!r}")
        assert approved_fields(ma) == approved_fields(expected), manifest_name
