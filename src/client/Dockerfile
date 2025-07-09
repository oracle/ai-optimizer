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

RUN microdnf --nodocs -y update && \
    microdnf --nodocs -y install python3.11 python3.11-pip && \
    microdnf clean all && \
    python3.11 -m venv --symlinks --upgrade-deps /opt/.venv && \
    groupadd $RUNUSER && \
    useradd -u 10001 -g $RUNUSER -md /app $RUNUSER
RUN for dir in server client common; do \
      install -d -m 0700 -o $RUNUSER -g $RUNUSER /opt/package/$dir; \
    done

COPY pyproject.toml /opt/package/pyproject.toml

RUN /opt/.venv/bin/pip install --no-cache-dir "/opt/package[client]"

##################################################
# Clint Application
##################################################
FROM optimizer_base AS client

ENV TEMP=/app/tmp

# Prep the app directory
RUN for dir in $TEMP; do \
      install -d -m 0700 -o $RUNUSER -g $RUNUSER $dir; \
    done
COPY --chown=$RUNUSER:$RUNUSER . /app/
RUN rm -rf /app/server /app/launch_server.py 

# Set user and working directory
USER $RUNUSER
WORKDIR /app/

RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
