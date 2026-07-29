## Copyright (c) 2024, 2026, Oracle and/or its affiliates.
## Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker:disable
##################################################
# Stage 1: Base — shared by builder and runtime
# Build from the project root directory:
#  podman build -f src/server/Dockerfile -t ai-optimizer-server:latest .
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
    uv --project /app sync --locked --no-install-project --extra server --extra otel

# Install this project after its source is available.
COPY src /app/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv --project /app sync --locked --extra server --extra otel

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

# The venv's interpreter links to uv-managed Python, so copy both.
COPY --from=builder /opt/uv/python /opt/uv/python
COPY --from=builder --chown=$RUNUSER:$RUNUSER $VIRTUAL_ENV $VIRTUAL_ENV

# Single source copy into the final image
COPY --chown=$RUNUSER:$RUNUSER src /app/src
RUN rm -rf /app/src/client

# Mount points (supply via -v at runtime):
# - /app/.oci      — OCI config (read-only); entrypoint copies to /app/runtime/.oci
# - /app/tns_admin — Oracle TNS admin directory

# Set user and working directory
EXPOSE 8000
USER $RUNUSER
WORKDIR /app/
ENTRYPOINT ["/app/src/entrypoint.py"]
