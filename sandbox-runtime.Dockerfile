# syntax=docker/dockerfile:1.7
#
# Build example:
#   docker buildx build \
#     --build-arg BASE_IMAGE=<gke-agent-sandbox-runtime-base> \
#     --secret id=APT_AUTH,src=/path/to/apt-auth.conf \
#     --secret id=PIP_CONFIG,src=/path/to/pip.conf \
#     -f sandbox-runtime.Dockerfile .
#
# PIP_CONFIG is optional. Use it for the private Nexus/PyPI index rather than
# passing credentials as build arguments, so credentials are not baked into an
# image layer.

ARG BASE_IMAGE
FROM ${BASE_IMAGE}

# BASE_IMAGE is the existing Agent Sandbox runtime-service image. It owns
# /app/main.py, its application environment, exposed port and entrypoint.
# This file only layers Skill dependencies and the agent workspace onto it.

ARG TZ=Etc/UTC
ARG PYTHON_BIN=python3.12
ARG SANDBOX_UID=1000

USER root
RUN mkdir -p /app
WORKDIR /app

# The base image is expected to be Debian/Ubuntu compatible. APT_AUTH is an
# optional BuildKit secret for authenticated internal APT repositories.
RUN --mount=type=secret,id=APT_AUTH,target=/etc/apt/auth.conf,required=false \
    ln -snf "/usr/share/zoneinfo/${TZ}" /etc/localtime \
    && echo "${TZ}" > /etc/timezone \
    && apt-get update -yq \
    && apt-get install -yq --no-install-recommends \
        bash \
        ca-certificates \
        coreutils \
        findutils \
        grep \
        libnsl1 \
        python3.12 \
        python3.12-dev \
        python3.12-venv \
        python3-setuptools \
    && apt-get autoremove -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/*

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# The repository keeps build/root.cer as a local-build placeholder, so it may
# be empty. CI should replace it with the enterprise PEM before image build.
# Pip uses the file directly; when it is a PEM it is also added to the OS store.
COPY build/root.cer /opt/deepagent/certs/root.cer
RUN if [[ -s /opt/deepagent/certs/root.cer ]]; then \
        cp /opt/deepagent/certs/root.cer /usr/local/share/ca-certificates/deepagent-root.crt; \
        update-ca-certificates; \
    else \
        echo "No enterprise CA supplied; using the base image trust store"; \
    fi

# Do not install the API application's requirements here: that service already
# lives in BASE_IMAGE under /app. Each installed Skill may declare its own
# requirements.txt.
COPY skill-packages /workspace/skill-packages

# PIP_CONFIG can contain the internal index-url, extra-index-url and cert
# settings. It is mounted only for this command and is never present in the
# resulting image. A build without the secret uses pip's normal public index.
RUN --mount=type=secret,id=PIP_CONFIG,target=/etc/pip.conf,required=false \
    ${PYTHON_BIN} -m venv /opt/skill-venv \
    && if [[ -s /opt/deepagent/certs/root.cer ]]; then export PIP_CERT=/opt/deepagent/certs/root.cer; fi \
    && /opt/skill-venv/bin/python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && find /workspace/skill-packages -type f -name requirements.txt -print0 \
    | sort -z \
    | while IFS= read -r -d '' requirements_file; do \
        echo "Installing Skill dependencies from ${requirements_file}"; \
        /opt/skill-venv/bin/python -m pip install --no-cache-dir -r "${requirements_file}"; \
    done \
    && rm -rf /root/.cache/pip

# Skill packages are immutable to the runtime user. /work holds reusable
# intermediate files; /output is the only directory publish_artifact exposes.
RUN mkdir -p /workspace/work /workspace/output \
    && ln -s /workspace/skill-packages /skill-packages \
    && ln -s /workspace/work /work \
    && ln -s /workspace/output /output \
    && chown -R root:root /workspace/skill-packages /opt/skill-venv \
    && chmod -R a+rX /workspace/skill-packages /opt/skill-venv \
    && chmod -R a-w /workspace/skill-packages /opt/skill-venv \
    && chown -R ${SANDBOX_UID}:${SANDBOX_UID} /workspace/work /workspace/output

ENV SANDBOX_BASE_DIR=/workspace \
    DEEPAGENT_WORKSPACE=/workspace \
    VIRTUAL_ENV=/opt/skill-venv \
    PATH=/opt/skill-venv/bin:${PATH}

WORKDIR /app
USER ${SANDBOX_UID}
