# CI V3 Phase 3B execution image. Built from the repository root as the build context.
# BASE_IMAGE must be an independently reviewed Python 3.12 image at an immutable digest.
# Publishing is a separate owner operation; this file never pushes anything.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER root
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1 \
    OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
# nodejs and openssh-client are present on the hosted control runner; tests skip without them (coverage loss).
RUN apt-get update && apt-get install -y --no-install-recommends git libgomp1 nodejs openssh-client \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY requirements.txt requirements-ci-tests.txt constraints.txt ./
# An optional build-only CA bundle (BuildKit secret "build_ca") supports TLS-inspecting build networks.
# It is mounted, never copied into a layer, and absent in the default build.
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi \
    && python -m pip install -r requirements.txt -c constraints.txt \
    && python -m pip install -r requirements-ci-tests.txt -c constraints.txt \
    && python -m pip check
# Resolved dependency evidence is part of the immutable image content.
RUN mkdir -p /opt/ci-v3 \
    && python -m pip freeze --all > /opt/ci-v3/resolved-python.txt \
    && dpkg-query -W -f='${Package}=${Version}\n' | sort > /opt/ci-v3/resolved-system.txt \
    && python -VV > /opt/ci-v3/python-version.txt \
    && { node --version; ssh-keygen -V 2>&1 | head -1 || true; } > /opt/ci-v3/tool-versions.txt 2>&1 \
    && chmod -R a=rX /opt/ci-v3 \
    && rm -rf /build
WORKDIR /subject
# Runtime always supplies the host numeric non-root UID/GID, no network and restricted mounts.
