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

RUN microdnf --nodocs -y update && \
    microdnf --nodocs -y install python3.11 python3.11-pip && \
    microdnf clean all && \
    python3.11 -m venv --symlinks --upgrade-deps /opt/.venv && \
    groupadd $RUNUSER && \
    useradd -u 10001 -g $RUNUSER -md /app $RUNUSER
RUN for dir in server client common; do \
      install -d -m 0700 -o $RUNUSER -g $RUNUSER /opt/package/$dir; \
    done

# Copy only pyproject.toml for dependency installation
COPY pyproject.toml /opt/package/pyproject.toml
# Use the virtual environment for pip installations
RUN /opt/.venv/bin/pip install --upgrade pip wheel setuptools && \
    /opt/.venv/bin/pip install torch==2.8.0+cpu -f https://download.pytorch.org/whl/cpu/torch && \
    /opt/.venv/bin/pip install --no-cache-dir "/opt/package[all]"

##################################################
# Application
##################################################
FROM all_in_one_pyenv AS oai_application
ENV PATH=/opt/.venv/bin:$PATH
ENV TEMP=/app/tmp
ENV TNS_ADMIN=/app/tns_admin
ENV API_SERVER_CONTROL="TRUE"
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

# Set user and working directory
USER $RUNUSER
WORKDIR /app/

RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
