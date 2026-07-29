## Copyright (c) 2024, 2026, Oracle and/or its affiliates.
## Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker:disable
##################################################
# Stage 1: Base — shared by builder and runtime
# Build from the project root directory:
#  podman build -f src/client/Dockerfile -t ai-optimizer-client:latest .
##################################################
FROM container-registry.oracle.com/os/oraclelinux:9-slim AS base

##################################################
# Stage 2: Builder — venv + Python dependencies
##################################################
FROM base AS builder

ENV VIRTUAL_ENV=/app/.venv \
    UV_PYTHON_INSTALL_DIR=/opt/uv/python \
    UV_LINK_MODE=copy

# pip is only the bootstrap mechanism for uv.
RUN microdnf --nodocs -y install python3-pip && \
    pip3 install --no-cache-dir uv && \
    microdnf remove -y python3-pip && \
    microdnf clean all

# Cache third-party dependencies independently of source changes.
COPY pyproject.toml uv.lock .python-version /app/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv --project /app sync --locked --no-install-project --extra client

# Install this project after its source is available.
COPY src /app/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv --project /app sync --locked --extra client

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

# Runtime: runuser and app dirs
RUN groupadd -g 10001 $RUNUSER && \
    useradd -u 10001 -g $RUNUSER -md /app $RUNUSER && \
    for dir in $TEMP; do \
        install -d -m 0700 -o $RUNUSER -g $RUNUSER $dir; \
    done

# The venv's interpreter links to uv-managed Python, so copy both.
COPY --from=builder /opt/uv/python /opt/uv/python
COPY --from=builder --chown=$RUNUSER:$RUNUSER $VIRTUAL_ENV $VIRTUAL_ENV

# Single source copy into the final image
COPY --chown=$RUNUSER:$RUNUSER src /app/src
RUN rm -rf /app/src/server

# Set user and working directory
EXPOSE 8501
USER $RUNUSER
WORKDIR /app/
ENTRYPOINT ["/app/src/entrypoint.py"]
