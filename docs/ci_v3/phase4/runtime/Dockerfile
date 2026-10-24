FROM ubuntu@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac
ENV DEBIAN_FRONTEND=noninteractive PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates python3.12 python3.12-venv gcc gcc-13=13.3.0-6ubuntu2~24.04.1 libc6-dev binutils libasan8 libubsan1 libgomp1 git nodejs openssh-client && rm -rf /var/lib/apt/lists/*
RUN python3.12 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /build
COPY requirements.txt requirements-ci-tests.txt constraints.txt ./
COPY docs/ci_v3/phase4/runtime/python.lock ./python.lock
RUN --mount=type=secret,id=build_ca,required=false if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi && python -m pip install -r python.lock && python -m pip install -r requirements.txt -c constraints.txt && python -m pip install -r requirements-ci-tests.txt -c constraints.txt && python -m pip check
RUN mkdir -p /opt/ci-v3 && python -m pip freeze --all > /opt/ci-v3/resolved-python.txt && dpkg-query -W -f='${Package}=${Version}\n' | sort > /opt/ci-v3/resolved-system.txt && python -VV > /opt/ci-v3/python-version.txt && { gcc --version; as --version; ld --version; node --version; ssh -V 2>&1; } > /opt/ci-v3/tool-versions.txt && cp /etc/os-release /opt/ci-v3/os-release.txt && chmod -R a=rX /opt/ci-v3 && rm -rf /build
WORKDIR /subject
USER 1000:1000
