## Copyright (c) 2024, 2025, Oracle and/or its affiliates.
## Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
#############################################################
# Base - Web GUI
# Build from the app/ directory:
#  podman build -f client/Dockerfile -t ai-optimizer-client:0.1.0 .
#############################################################
FROM container-registry.oracle.com/os/oraclelinux:8-slim AS client_pyenv

ENV RUNUSER=oracleai

# Combine related commands into a single RUN layer to minimize image layers
RUN microdnf -y update && \
    microdnf -y install python3.11 python3.11-pip && \
    microdnf clean all && \
    python3.11 -m venv --symlinks --upgrade-deps /opt/.venv && \
    groupadd $RUNUSER && \
    useradd -u 10001 -g $RUNUSER -md /app $RUNUSER && \
    install -d -m 0700 -o $RUNUSER -g $RUNUSER /app/tmp && \
    install -d -m 0700 -o $RUNUSER -g $RUNUSER /opt/package/client && \
    install -d -m 0700 -o $RUNUSER -g $RUNUSER /opt/package/server && \
    install -d -m 0700 -o $RUNUSER -g $RUNUSER /opt/package/common

# Copy only pyproject.toml for dependency installation
COPY pyproject.toml /opt/package/pyproject.toml

# Use the virtual environment for pip installations
RUN source /opt/.venv/bin/activate && \
    pip install --upgrade pip wheel setuptools && \
    pip install "/opt/package[client]"

##################################################
# Application
##################################################
FROM client_pyenv AS client
ENV PATH=/opt/.venv/bin:$PATH
ENV TEMP=/app/tmp

COPY --chown=$RUNUSER:$RUNUSER . /app
RUN rm -rf /app/server /app/.oci /app/launch_server.py

# Set user and working directory
USER $RUNUSER
WORKDIR /app/

RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
