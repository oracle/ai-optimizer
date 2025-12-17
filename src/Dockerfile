## Copyright (c) 2024, 2025, Oracle and/or its affiliates.
## Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker:disable
##################################################
# Base - All-In-One
# Build from the project root directory:
#  podman build -f src/Dockerfile -t ai-optimizer-aio:latest .
##################################################
FROM container-registry.oracle.com/os/oraclelinux:8 AS all_in_one_pyenv
ENV RUNUSER=oracleai \
    VIRTUAL_ENV=/opt/.venv

RUN groupadd -g 10001 $RUNUSER && \
    useradd -u 10001 -g $RUNUSER -md /app $RUNUSER && \
    dnf config-manager --add-repo https://yum.oracle.com/repo/OracleLinux/OL8/oracle/software/\$basearch && \
    dnf --nodocs -y install python3.11 python3.11-pip sqlcl java-21-openjdk-headless --nogpgcheck && \
    dnf clean all && \
    python3.11 -m venv --symlinks --upgrade-deps $VIRTUAL_ENV

COPY pyproject.toml /opt/package/pyproject.toml

# Generate requirements and install deps only (cached layer)
RUN ${VIRTUAL_ENV}/bin/pip install --upgrade pip wheel setuptools uv && \
    ${VIRTUAL_ENV}/bin/uv pip install torch==2.9.1+cpu -f https://download.pytorch.org/whl/cpu/torch && \
    ${VIRTUAL_ENV}/bin/uv pip compile /opt/package/pyproject.toml --extra all -o /tmp/requirements.txt && \
    sed -i '/^torch==/d' /tmp/requirements.txt && \
    ${VIRTUAL_ENV}/bin/uv pip install -r /tmp/requirements.txt

# Copy source
COPY --chown=$RUNUSER:$RUNUSER src /opt/package/src

# Install project (deps already installed, so this is fast)
RUN ${VIRTUAL_ENV}/bin/uv pip install "/opt/package[all]"
##################################################
# Application
##################################################
FROM all_in_one_pyenv AS oai_application
ENV PATH=$VIRTUAL_ENV/bin:$PATH \
    TEMP=/app/tmp \
    TNS_ADMIN=/app/tns_admin \
    OCI_CLI_CONFIG_FILE=/app/runtime/.oci/config \
    TOKENIZERS_PARALLELISM=true \
    NUMBA_CACHE_DIR=/app/tmp \
    MPLCONFIGDIR=/app/tmp \
    TIKTOKEN_CACHE_DIR=/app/tmp \
    NLTK_DATA=/app/tmp \
    API_SERVER_CONTROL="TRUE"

# Expect the .oci directory to be mounted to /app/.oci
VOLUME ["/app/.oci"]
# Expect the TNS_ADMIN directory to be mounted to /app/tns_admin
VOLUME ["/app/tns_admin"]

# Prep the app directory
RUN for dir in $TEMP $TNS_ADMIN $(dirname $OCI_CLI_CONFIG_FILE); do \
      install -d -m 0700 -o $RUNUSER -g $RUNUSER $dir; \
    done
COPY --chown=$RUNUSER:$RUNUSER src /app/

# Set user and working directory
USER $RUNUSER
WORKDIR /app/

RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
