## Copyright (c) 2024, 2025, Oracle and/or its affiliates.
## Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
#############################################################
# Base - API Server
# Build from the src/ directory:
#  podman build -f server/Dockerfile -t ai-optimizer-server:latest .
#############################################################
# spell-checker: disable
FROM container-registry.oracle.com/os/oraclelinux:8-slim AS optimizer_base

ENV RUNUSER=oracleai
ENV PATH=/opt/.venv/bin:$PATH

RUN microdnf --nodocs -y update && \
    microdnf --nodocs -y install python3.11 python3.11-pip sqlcl && \
    microdnf clean all && \
    python3.11 -m venv --symlinks --upgrade-deps /opt/.venv && \
    groupadd $RUNUSER && \
    useradd -u 10001 -g $RUNUSER -md /app $RUNUSER
RUN for dir in server client common; do \
      install -d -m 0700 -o $RUNUSER -g $RUNUSER /opt/package/$dir; \
    done

COPY pyproject.toml /opt/package/pyproject.toml

RUN /opt/.venv/bin/pip install torch==2.8.0+cpu -f https://download.pytorch.org/whl/cpu/torch && \
    /opt/.venv/bin/pip install --no-cache-dir "/opt/package[server]"

##################################################
# Server Application
##################################################
FROM optimizer_base AS server

ENV TOKENIZERS_PARALLELISM=true
ENV NUMBA_CACHE_DIR=/app/tmp
ENV MPLCONFIGDIR=/app/tmp
ENV TIKTOKEN_CACHE_DIR=/app/tmp
ENV NLTK_DATA=/app/tmp
ENV TEMP=/app/tmp
ENV TNS_ADMIN=/app/tns_admin
ENV OCI_CLI_CONFIG_FILE=/app/runtime/.oci/config

# Expect the .oci directory to be mounted to /app/.oci
VOLUME ["/app/.oci"]
# Expect the TNS_ADMIN directory to be mounted to /app/tns_admin
VOLUME ["/app/tns_admin"]

# Prep the app directory
RUN for dir in $TEMP $TNS_ADMIN $(dirname $OCI_CLI_CONFIG_FILE); do \
      install -d -m 0700 -o $RUNUSER -g $RUNUSER $dir; \
    done
COPY --chown=$RUNUSER:$RUNUSER . /app/
RUN rm -rf /app/client /app/.streamlit /app/launch_client.py

# Set user and working directory
USER $RUNUSER
WORKDIR /app/

RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
