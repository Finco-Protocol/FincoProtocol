# Image build/publish is a separate owner operation, never performed by this PR.
# BASE_IMAGE must be an independently reviewed Python 3.12 image at an immutable digest.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER root
RUN apt-get update && apt-get install -y --no-install-recommends git libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY requirements.txt requirements-ci-tests.txt constraints.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt -c constraints.txt \
    && python -m pip install --no-cache-dir -r requirements-ci-tests.txt -c constraints.txt \
    && python -m pip check
WORKDIR /subject
# Runtime always supplies the host numeric non-root UID/GID and restricted mounts.
