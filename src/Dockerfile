## Copyright (c) 2024, 2025, Oracle and/or its affiliates.
## Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
##################################################
# Base - All-In-One
##################################################
FROM container-registry.oracle.com/os/oraclelinux:8-slim AS all_in_one_pyenv

# NUMBA_DISABLE_JIT is for Apple Silicon support
ENV TOKENIZERS_PARALLELISM=true \
    NUMBA_DISABLE_JIT=1 \
    RUNUSER=oracleai

# Combine related commands into a single RUN layer to minimize image layers
RUN microdnf --nodocs -y update && \
    microdnf --nodocs -y install python3.11 python3.11-pip && \
    microdnf clean all && \
    python3.11 -m venv --symlinks --upgrade-deps /opt/.venv && \
    groupadd $RUNUSER && \
    useradd -u 10001 -g $RUNUSER -md /app $RUNUSER && \
    install -d -m 0700 -o $RUNUSER -g $RUNUSER /app/.oci && \
    install -d -m 0700 -o $RUNUSER -g $RUNUSER /app/tmp && \
    install -d -m 0700 -o $RUNUSER -g $RUNUSER /opt/package/server && \
    install -d -m 0700 -o $RUNUSER -g $RUNUSER /opt/package/client && \
    install -d -m 0700 -o $RUNUSER -g $RUNUSER /opt/package/common
    
# Copy only pyproject.toml for dependency installation
COPY pyproject.toml /opt/package/pyproject.toml
# Use the virtual environment for pip installations
RUN /opt/.venv/bin/pip install --upgrade pip wheel setuptools && \
    /opt/.venv/bin/pip install torch==2.7.1+cpu -f https://download.pytorch.org/whl/cpu/torch && \
    /opt/.venv/bin/pip install --no-cache-dir "/opt/package[all]"

##################################################
# Application
##################################################
FROM all_in_one_pyenv AS oai_application
ENV PATH=/opt/.venv/bin:$PATH
ENV TEMP=/app/tmp

COPY --chown=$RUNUSER:$RUNUSER . /app/
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
