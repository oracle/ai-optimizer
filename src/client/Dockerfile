## Copyright (c) 2024, 2025, Oracle and/or its affiliates.
## Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker: disable
#############################################################
# Base - Web GUI
# Build from the / directory:
#  podman build -f src/client/Dockerfile -t ai-optimizer-client:latest .
#############################################################
FROM container-registry.oracle.com/os/oraclelinux:8-slim AS optimizer_base
ENV RUNUSER=oracleai \
    VIRTUAL_ENV=/opt/.venv

RUN groupadd $RUNUSER && \
    useradd -u 10001 -g $RUNUSER -md /app $RUNUSER && \
    microdnf --nodocs -y install python3.11 python3.11-pip python3.11-devel && \
    microdnf clean all && \
    python3.11 -m venv --symlinks --upgrade-deps $VIRTUAL_ENV

COPY --chown=$RUNUSER:$RUNUSER src /opt/package/src
COPY pyproject.toml /opt/package/pyproject.toml

RUN ${VIRTUAL_ENV}/bin/pip install --upgrade pip wheel setuptools uv && \
    ${VIRTUAL_ENV}/bin/uv pip install "/opt/package[client]"

##################################################
# Clint Application
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
