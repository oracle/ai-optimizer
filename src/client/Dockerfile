## Copyright (c) 2024, 2025, Oracle and/or its affiliates.
## Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
#############################################################
# Base - Web GUI
# Build from the src/ directory:
#  podman build -f client/Dockerfile -t ai-optimizer-client:latest .
#############################################################
# spell-checker: disable
FROM container-registry.oracle.com/os/oraclelinux:8-slim AS optimizer_base

ENV RUNUSER=oracleai
ENV PATH=/opt/.venv/bin:$PATH
ENV TEMP=/app/tmp

# Combine related commands into a single RUN layer to minimize image layers
RUN microdnf -y update && \
    microdnf -y install python3.11 python3.11-pip && \
    microdnf clean all && \
    python3.11 -m venv --symlinks --upgrade-deps /opt/.venv && \
    /opt/.venv/bin/pip install --upgrade pip wheel setuptools && \
    groupadd $RUNUSER && \
    useradd -u 10001 -g $RUNUSER -md /app $RUNUSER && \
    install -d -m 0700 -o $RUNUSER -g $RUNUSER /app/tmp && \
    install -d -m 0700 -o $RUNUSER -g $RUNUSER /opt/package/client && \
    install -d -m 0700 -o $RUNUSER -g $RUNUSER /opt/package/server && \
    install -d -m 0700 -o $RUNUSER -g $RUNUSER /opt/package/common && \
    install -d -m 0700 -o $RUNUSER -g $RUNUSER /app/.oci

COPY pyproject.toml /opt/package/pyproject.toml

RUN /opt/.venv/bin/pip install "/opt/package[client]"

##################################################
# Clint Application
##################################################
FROM optimizer_base AS client

COPY . /app
RUN rm -rf /app/server /app/.oci /app/launch_server.py && \
    chown -R oracleai:oracleai /app

# Set user and working directory
USER $RUNUSER
WORKDIR /app/

RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
