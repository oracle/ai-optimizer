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
ENV TEMP=/app/tmp

# Combine related commands into a single RUN layer to minimize image layers
RUN microdnf --nodocs -y update && \
    microdnf --nodocs -y install python3.11 python3.11-pip && \
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

RUN /opt/.venv/bin/pip install torch==2.7.1+cpu -f https://download.pytorch.org/whl/cpu/torch && \
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

COPY . /app
RUN rm -rf /app/client /app/.streamlit /app/launch_client.py && \
    chown -R oracleai:oracleai /app

# Remove the OCI file if not development; update the key path if so
ENV ENVIRONMENT=${ENVIRONMENT}
RUN if [ -d "/app/.oci" ] && [ "$ENVIRONMENT" != "development" ]; then \
        rm -rf /app/.oci; \
    else \
        sed -i 's|/.*/\(.*\.pem\)|/app/.oci/\1|g' /app/.oci/config; \
    fi

# Set user and working directory
USER $RUNUSER
WORKDIR /app/

RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
