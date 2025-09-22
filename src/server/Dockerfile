## Copyright (c) 2024, 2025, Oracle and/or its affiliates.
## Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
#############################################################
# Base - API Server
# Build from the / directory:
#  podman build -f src/server/Dockerfile -t ai-optimizer-server:latest .
#############################################################
# spell-checker: disable
FROM container-registry.oracle.com/os/oraclelinux:8-slim AS optimizer_base

ENV RUNUSER=oracleai
ENV RUNUSER=oracleai \
    VIRTUAL_ENV=/opt/.venv

RUN groupadd $RUNUSER && \
    useradd -u 10001 -g $RUNUSER -md /app $RUNUSER && \
    microdnf --nodocs -y install python3.11 python3.11-pip python3.11-devel gcc gcc-c++ && \
    microdnf clean all && \
    python3.11 -m venv --symlinks --upgrade-deps $VIRTUAL_ENV

COPY --chown=$RUNUSER:$RUNUSER src /opt/package/src
COPY pyproject.toml /opt/package/pyproject.toml

RUN ${VIRTUAL_ENV}/bin/pip install --upgrade pip wheel setuptools uv && \
    ${VIRTUAL_ENV}/bin/uv pip install torch==2.8.0+cpu -f https://download.pytorch.org/whl/cpu/torch && \
    ${VIRTUAL_ENV}/bin/uv pip install "/opt/package[server]"

##################################################
# Server Application
##################################################
FROM optimizer_base AS server
ENV PATH=$VIRTUAL_ENV/bin:$PATH \
    TEMP=/app/tmp \
    TNS_ADMIN=/app/tns_admin \
    OCI_CLI_CONFIG_FILE=/app/runtime/.oci/config \
    TOKENIZERS_PARALLELISM=true \
    NUMBA_CACHE_DIR=/app/tmp \
    MPLCONFIGDIR=/app/tmp \
    TIKTOKEN_CACHE_DIR=/app/tmp \
    NLTK_DATA=/app/tmp

# Expect the .oci directory to be mounted to /app/.oci
VOLUME ["/app/.oci"]
# Expect the TNS_ADMIN directory to be mounted to /app/tns_admin
VOLUME ["/app/tns_admin"]

# Prep the app directory
RUN for dir in $TEMP $TNS_ADMIN $(dirname $OCI_CLI_CONFIG_FILE); do \
      install -d -m 0700 -o $RUNUSER -g $RUNUSER $dir; \
    done
COPY --chown=$RUNUSER:$RUNUSER src /app/
RUN rm -rf /app/client /app/.streamlit /app/launch_client.py

# Set user and working directory
USER $RUNUSER
WORKDIR /app/

RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
