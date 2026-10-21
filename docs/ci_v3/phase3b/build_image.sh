#!/usr/bin/env bash
# Reproducible local/isolated image build and review-evidence capture. Never pushes to a registry.
# usage: build_image.sh BASE_IMAGE_WITH_DIGEST OUTPUT_DIR   (run from the repository root; optional BUILD_CA=/path/ca.pem)
set -euo pipefail
base="$1"; out="$2"
[[ "$base" =~ @sha256:[0-9a-f]{64}$ ]] || { echo "BASE_IMAGE must be an immutable digest" >&2; exit 2; }
mkdir -p "$out"
secret=(); [[ -n "${BUILD_CA:-}" ]] && secret=(--secret "id=build_ca,src=$BUILD_CA")
docker build "${secret[@]}" -f docs/ci_v3/phase3b/Dockerfile --build-arg "BASE_IMAGE=$base" -t finco-ci-v3:review .
digest="$(docker image inspect finco-ci-v3:review --format '{{.Id}}')"
docker run --rm finco-ci-v3:review sh -c 'cat /opt/ci-v3/resolved-python.txt' > "$out/resolved-python.txt"
docker run --rm finco-ci-v3:review sh -c 'cat /opt/ci-v3/resolved-system.txt' > "$out/resolved-system.txt"
docker run --rm finco-ci-v3:review sh -c 'id -u; cat /opt/ci-v3/python-version.txt' > "$out/runtime.txt"
git rev-parse HEAD > "$out/source-head.txt"
sha256sum requirements.txt requirements-ci-tests.txt constraints.txt docs/ci_v3/phase3b/Dockerfile > "$out/input-sha256.txt"
printf '{"base":"%s","image_id":"%s","note":"Registry digest exists only after an authorized push; the local id is review evidence"}\n' "$base" "$digest" > "$out/image.json"
cat "$out/image.json"
