"""Verify the F01 native image's recorded contents against this checkout's approved inputs (run INSIDE the image).

The image records its own resolved state under /opt/ci-v3 when built from docs/ci_v3/phase4/runtime/Dockerfile. A
BuildKit cache hit is only an optimization: this check proves the image actually in use carries the frontend lock of
this checkout, the pinned gcc-13, Ubuntu 24.04, Python 3.12 and every python.lock pin exactly.

Usage (in the container): python /subject/scripts/ci/native_image_identity.py --image-root /opt/ci-v3 --checkout /subject
"""
import argparse
import hashlib
import json
import pathlib
import re
import sys

GCC13 = "gcc-13=13.3.0-6ubuntu2~24.04.1"


def norm(name):
    return re.sub(r"[-_.]+", "-", name.split("[")[0].strip().lower())


def problems(image_root, checkout):
    img, src = pathlib.Path(image_root), pathlib.Path(checkout)
    out = []
    try:
        ident = json.loads((img / "frontend" / "identity.json").read_text())
    except (OSError, ValueError) as exc:
        return ["frontend identity.json unreadable: %s" % type(exc).__name__]
    for name in ("package.json", "package-lock.json"):
        want = hashlib.sha256((src / "frontend" / name).read_bytes()).hexdigest()
        if ident.get(name) != want:
            out.append("frontend %s in the image (%s) != checkout (%s)" % (name, ident.get(name), want))
    if GCC13 not in (img / "resolved-system.txt").read_text().split():
        out.append("pinned %s missing from the image" % GCC13)
    if "Ubuntu 24.04" not in (img / "os-release.txt").read_text():
        out.append("unexpected base OS")
    if not (img / "python-version.txt").read_text().startswith("Python 3.12"):
        out.append("unexpected Python")
    frozen = {}
    for line in (img / "resolved-python.txt").read_text().split():
        if "==" in line:
            pkg, ver = line.split("==", 1)
            frozen[norm(pkg)] = ver
    for raw in (src / "docs/ci_v3/phase4/runtime/python.lock").read_text().splitlines():
        line = raw.split("#")[0].split(";")[0].strip()
        if "==" in line:
            pkg, ver = line.split("==", 1)
            if frozen.get(norm(pkg)) != ver.strip():
                out.append("python.lock pin %s not installed exactly (image has %s)" % (line, frozen.get(norm(pkg))))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--image-root", default="/opt/ci-v3")
    ap.add_argument("--checkout", default="/subject")
    a = ap.parse_args(argv)
    found = problems(a.image_root, a.checkout)
    for p in found:
        print("NATIVE IMAGE IDENTITY FAILED:", p)
    if not found:
        print("native image identity ok: frontend lock, pinned gcc-13, Ubuntu 24.04, Python 3.12, python.lock pins")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
