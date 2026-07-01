## Copyright (c) 2024, 2026, Oracle and/or its affiliates.
## Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker:disable
##################################################
# Stage 1: Base — shared by builder and runtime
# Build from the project root directory:
#  podman build -f src/Dockerfile -t ai-optimizer-aio:latest .
##################################################
FROM container-registry.oracle.com/os/oraclelinux:9-slim AS base

RUN microdnf --nodocs -y install python3.11 && \
    microdnf clean all

##################################################
# Stage 2: Builder — venv + Python dependencies
##################################################
FROM base AS builder
ENV VIRTUAL_ENV=/app/.venv

RUN microdnf --nodocs -y install python3.11-pip && \
    python3.11 -m venv --symlinks --upgrade-deps $VIRTUAL_ENV && \
    microdnf -y remove python3.11-pip && microdnf clean all

COPY pyproject.toml /app/pyproject.toml

# Generate requirements and install deps only (cached layer)
# Avoid re-installing packages when only the source changes
RUN ${VIRTUAL_ENV}/bin/pip install --no-cache-dir uv && \
    ${VIRTUAL_ENV}/bin/pip install --no-cache-dir docling==2.108.0 --extra-index-url https://download.pytorch.org/whl/cpu && \
    ${VIRTUAL_ENV}/bin/uv pip compile /app/pyproject.toml --extra all \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        --index-strategy unsafe-best-match \
        -o /tmp/requirements.txt && \
    ${VIRTUAL_ENV}/bin/uv pip install -r /tmp/requirements.txt \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        --index-strategy unsafe-best-match

# Copy source and install project (deps already installed, so this is fast)
COPY src /app/src
RUN ${VIRTUAL_ENV}/bin/uv pip install "/app[all]" \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        --index-strategy unsafe-best-match && \
    # Remove build-only tools from venv (keep setuptools for pkg_resources)
    ${VIRTUAL_ENV}/bin/pip uninstall -y pip uv && \
    rm -rf ${VIRTUAL_ENV}/lib/python3.11/site-packages/pip* \
           ${VIRTUAL_ENV}/lib/python3.11/site-packages/uv-*.dist-info

##################################################
# Stage 3: Runtime
##################################################
FROM base AS application
ENV RUNUSER=oracleai \
    VIRTUAL_ENV=/app/.venv \
    PATH=/app/.venv/bin:$PATH \
    TEMP=/app/tmp \
    AIO_CLIENT_ADDRESS=0.0.0.0 \
    TNS_ADMIN=/app/tns_admin \
    NUMBA_CACHE_DIR=/app/tmp \
    MPLCONFIGDIR=/app/tmp \
    TIKTOKEN_CACHE_DIR=/app/tmp \
    NLTK_DATA=/app/tmp

# Runtime: oracle-software repo, runuser, runtime-only system packages, app dirs
RUN echo -e '[ol9_oracle_software]\n\
name=Oracle Software for OracleLinux 9\n\
baseurl=https://yum.oracle.com/repo/OracleLinux/OL9/oracle/software/$basearch\n\
gpgcheck=0\n\
enabled=1' > /etc/yum.repos.d/oracle-software.repo && \
    groupadd -g 10001 $RUNUSER && \
    useradd -u 10001 -g $RUNUSER -md /app $RUNUSER && \
    microdnf --nodocs -y install sqlcl java-21-openjdk-headless mesa-libGL && \
    microdnf clean all && \
    for dir in $TEMP $TNS_ADMIN /app/runtime/.oci; do \
        install -d -m 0700 -o $RUNUSER -g $RUNUSER $dir; \
    done

# Copy clean venv from builder (no pip/uv/wheel)
COPY --from=builder --chown=$RUNUSER:$RUNUSER $VIRTUAL_ENV $VIRTUAL_ENV

# Single source copy into the final image
COPY --chown=$RUNUSER:$RUNUSER src /app/src

# Mount points (supply via -v at runtime):
# - /app/.oci      — OCI config (read-only); entrypoint copies to /app/runtime/.oci
# - /app/tns_admin — Oracle TNS admin directory

# Set user and working directory
EXPOSE 8000 8501
USER $RUNUSER
WORKDIR /app/
ENTRYPOINT ["/app/src/entrypoint.py"]
