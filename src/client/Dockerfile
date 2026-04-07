## Copyright (c) 2024, 2026, Oracle and/or its affiliates.
## Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker:disable
##################################################
# Stage 1: Base — shared by builder and runtime
# Build from the project root directory:
#  podman build -f src/client/Dockerfile -t ai-optimizer-client:latest .
##################################################
FROM container-registry.oracle.com/os/oraclelinux:8 AS base

RUN dnf --nodocs -y install python3.11 && \
    dnf clean all

##################################################
# Stage 2: Builder — venv + Python dependencies
##################################################
FROM base AS builder
ENV VIRTUAL_ENV=/app/.venv

RUN dnf --nodocs -y install python3.11-pip && \
    python3.11 -m venv --symlinks --upgrade-deps $VIRTUAL_ENV && \
    dnf -y remove python3.11-pip && dnf clean all

COPY pyproject.toml /app/pyproject.toml

# Generate requirements and install deps only (cached layer)
# Avoid re-installing packages when only the source changes
RUN ${VIRTUAL_ENV}/bin/pip install --no-cache-dir wheel uv && \
    ${VIRTUAL_ENV}/bin/uv pip compile /app/pyproject.toml --extra client -o /tmp/requirements.txt && \
    ${VIRTUAL_ENV}/bin/uv pip install -r /tmp/requirements.txt

# Copy source and install project (deps already installed, so this is fast)
COPY src /app/src
RUN ${VIRTUAL_ENV}/bin/uv pip install "/app[client]" && \
    # Remove build-only tools from venv (keep setuptools for pkg_resources)
    ${VIRTUAL_ENV}/bin/pip uninstall -y pip wheel uv && \
    rm -rf ${VIRTUAL_ENV}/lib/python3.11/site-packages/pip* \
           ${VIRTUAL_ENV}/lib/python3.11/site-packages/wheel* \
           ${VIRTUAL_ENV}/lib/python3.11/site-packages/uv-*.dist-info

##################################################
# Stage 3: Runtime
##################################################
FROM base AS application
ENV RUNUSER=oracleai \
    VIRTUAL_ENV=/app/.venv \
    PATH=/app/.venv/bin:$PATH \
    TEMP=/app/tmp \
    MPLCONFIGDIR=/app/tmp \
    AIO_CLIENT_ADDRESS=0.0.0.0

# Runtime-only system packages (python3.11 already in base)
RUN groupadd -g 10001 $RUNUSER && \
    useradd -u 10001 -g $RUNUSER -md /app $RUNUSER

# Prep the app directory
RUN for dir in $TEMP; do \
    install -d -m 0700 -o $RUNUSER -g $RUNUSER $dir; \
    done

# Copy clean venv from builder (no pip/uv/wheel)
COPY --from=builder --chown=$RUNUSER:$RUNUSER $VIRTUAL_ENV $VIRTUAL_ENV

# Single source copy into the final image
COPY --chown=$RUNUSER:$RUNUSER src /app/src
RUN rm -rf /app/src/server

# Set user and working directory
EXPOSE 8501
USER $RUNUSER
WORKDIR /app/
RUN chmod +x /app/src/entrypoint.py
ENTRYPOINT ["/app/src/entrypoint.py"]
