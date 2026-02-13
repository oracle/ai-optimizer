## Copyright (c) 2024, 2026, Oracle and/or its affiliates.
## Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker: disable
#############################################################
# Base - Web GUI
# Build from the project root directory:
#  podman build -f src/client/Dockerfile -t ai-optimizer-client:latest .
#############################################################
FROM container-registry.oracle.com/os/oraclelinux:8 AS optimizer_base
ENV RUNUSER=oracleai \
    VIRTUAL_ENV=/opt/.venv

RUN groupadd -g 10001 $RUNUSER && \
    useradd -u 10001 -g $RUNUSER -md /app $RUNUSER && \
    dnf --nodocs -y install python3.11 python3.11-pip && \
    dnf clean all && \
    python3.11 -m venv --symlinks --upgrade-deps $VIRTUAL_ENV

COPY pyproject.toml /opt/package/pyproject.toml

# Generate requirements and install deps only (cached layer)
RUN ${VIRTUAL_ENV}/bin/pip install --upgrade pip wheel setuptools uv && \
    ${VIRTUAL_ENV}/bin/uv pip compile /opt/package/pyproject.toml --extra client -o /tmp/requirements.txt && \
    ${VIRTUAL_ENV}/bin/uv pip install -r /tmp/requirements.txt

# Copy source
COPY --chown=$RUNUSER:$RUNUSER src /opt/package/src

# Install project (deps already installed, so this is fast)
RUN ${VIRTUAL_ENV}/bin/uv pip install "/opt/package[client]"

##################################################
# Client Application
##################################################
FROM optimizer_base AS client
ENV PATH=$VIRTUAL_ENV/bin:$PATH \
    TEMP=/app/tmp

# Prep the app directory
RUN for dir in $TEMP; do \
      install -d -m 0700 -o $RUNUSER -g $RUNUSER $dir; \
    done

COPY --chown=$RUNUSER:$RUNUSER src /app/
RUN rm -rf /app/server /app/launch_server.py 

# Set user and working directory
USER $RUNUSER
WORKDIR /app/

RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
