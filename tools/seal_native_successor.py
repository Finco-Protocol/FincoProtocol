"""Reviewed native provenance SUCCESSOR seal (Correction E). Reads the genuine ``build_manifest`` of the current tree.

    python -m tools.seal_native_successor           # report drift only
    python -m tools.seal_native_successor --write   # rewrite the approved-blob manifests and the impacted build manifests

Only the approved-blob manifests whose sources actually changed are rewritten, and only through the repository's own
``provenance.build_manifest`` / ``build`` mechanisms; compiler, flags, ABI and kernels are untouched, so artifact SHA-256 and build
IDs must stay equal to the committed ones (the script refuses to write otherwise).
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    from financial_engine.native_v10 import build, build_stage2, provenance as P
    from financial_engine.native_v11 import build_stage3, stage3 as S3

    n10, n11 = ROOT / "financial_engine/native_v10", ROOT / "financial_engine/native_v11"
    stages = (
        ("stage1", n10 / "approved_canonical_blobs.json", None, None, build, n10 / "fk_v10_manifest.json", False),
        ("stage2", n10 / "approved_canonical_blobs_stage2.json", P.STAGE2_REGION_FUNCTIONS, P.STAGE2_EXTRA_SOURCES, build_stage2,
         n10 / "fk_v10_stage2_manifest.json", False),
        ("stage3", n11 / "approved_canonical_blobs_stage3.json", S3.STAGE3_REGION_FUNCTIONS, S3.STAGE3_EXTRA_SOURCES, build_stage3,
         n11 / "fk_v11_stage3_manifest.json", True),
    )
    status = 0
    for name, approved, funcs, extra, builder, build_manifest_path, trailing_nl in stages:
        old = json.loads(approved.read_text())
        new = P.build_manifest(funcs, extra)
        drift = {k: (old["blobs"].get(k), new["blobs"].get(k)) for k in sorted(set(old["blobs"]) | set(new["blobs"]))
                 if old["blobs"].get(k) != new["blobs"].get(k)}
        print(name, "drift:", json.dumps(drift, indent=1) if drift else "none")
        if not drift:
            continue
        if not args.write:
            status = 1
            continue
        text = json.dumps(new, indent=1, sort_keys=True) + ("\n" if trailing_nl else "")
        approved.write_text(text, encoding="utf-8")
        committed = json.loads(build_manifest_path.read_text())
        with tempfile.TemporaryDirectory() as tmp:
            produced = builder.build(Path(tmp))
        for field in ("artifact_sha256", "build_id", "source_sha256", "abi_version", "compiler", "flags", "target", "variant"):
            if produced.get(field) != committed.get(field):
                print(f"REFUSED {name}: {field} differs from the committed reviewed value; nothing else was rewritten")
                approved.write_text(json.dumps(old, indent=1, sort_keys=True) + ("\n" if trailing_nl else ""), encoding="utf-8")
                return 2
        build_manifest_path.write_text(json.dumps(produced, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"{name}: approved blobs sha256 {committed['approved_blobs_sha256'][:12]} -> {produced['approved_blobs_sha256'][:12]}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
