#cloud-config
# Copyright (c) 2024, 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker: disable
users:
  - default
  - name: oracleai
    uid: 10001
    shell: /bin/bash
    homedir: /app

package_update: false
# Packages are installed via /tmp/install_packages.sh in runcmd (with DNS wait
# and dnf retries). The cloud-config `packages:` module fires before the OCI
# VCN resolver is reliably ready, causing intermittent metadata-download
# failures against yum.<region>.oci.oraclecloud.com.

write_files:
  - path: /etc/systemd/system/ai-optimizer.service
    permissions: '0644'
    content: |
      [Unit]
      Description=AI Optimizer and Toolkit
      After=network.target

      [Service]
      Type=simple
      ExecStart=/app/.venv/bin/python /app/src/entrypoint.py client
      User=oracleai
      Group=oracleai
      WorkingDirectory=/app/src
      Environment="HOME=/app"
      Environment="AIO_ENV=vm"
      Environment="TNS_ADMIN=/app/tns_admin"
      Environment="VIRTUAL_ENV=/app/.venv"
      Environment="PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin"
      Restart=on-failure

      [Install]
      WantedBy=multi-user.target

  - path: /tmp/install_packages.sh
    permissions: '0755'
    content: |
      #!/bin/bash
      # Wait for DNS to be ready, then dnf install with retries.
      # Works around an OCI cloud-init race where the VCN resolver isn't
      # serving queries by the time dnf hits the regional yum mirror.
      set -u
      PKGS="$@"
      RESOLVE_HOST="yum.oracle.com"
      REGION=$(curl -fsS -m 5 -H "Authorization: Bearer Oracle" \
        http://169.254.169.254/opc/v2/instance/region 2>/dev/null || true)
      if [ -n "$REGION" ]; then
        RESOLVE_HOST="yum.$REGION.oci.oraclecloud.com"
      fi
      for i in $(seq 1 60); do
        getent hosts "$RESOLVE_HOST" >/dev/null 2>&1 && break
        sleep 2
      done
      for attempt in 1 2 3 4 5; do
        dnf install -y $PKGS && exit 0
        echo "dnf install attempt $attempt failed; cleaning and retrying"
        dnf clean all || true
        sleep 10
      done
      exit 1

  - path: /tmp/root_setup.sh
    permissions: '0755'
    content: |
      #!/bin/env bash
      mkdir -p /app
      chown oracleai:oracleai /app
      if ${install_ollama}; then
        curl -fsSL https://ollama.com/install.sh | sh
        systemctl enable ollama
        systemctl daemon-reload
        systemctl restart ollama
      fi
      systemctl stop firewalld.service
      firewall-offline-cmd --zone=public --add-port 8501/tcp
      firewall-offline-cmd --zone=public --add-port 8000/tcp
      systemctl start firewalld.service

  - path: /tmp/app_setup.sh
    permissions: '0755'
    content: |
      #!/bin/bash
      # Download/Setup Source Code
      # --retry/--retry-connrefused: tolerate transient DNS/connect failures
      # immediately after boot while the VCN resolver settles.
      CURL_OPTS="-fsSL --retry 10 --retry-delay 5 --retry-connrefused --retry-all-errors"
      if [ "${optimizer_version}" = "Stable" ]; then
          echo "Downloading Code from LATEST release"
          curl $CURL_OPTS "https://github.com/oracle/ai-optimizer/releases/latest/download/ai-optimizer-src.tar.gz" \
            | tar -xz -C /app
      else
          echo "Downloading Code from branch: ${optimizer_branch}"
          mkdir -p /tmp/src-archive
          curl $CURL_OPTS "https://github.com/oracle/ai-optimizer/archive/refs/heads/${optimizer_branch}.tar.gz" \
            | tar -xz -C /tmp/src-archive
          mv /tmp/src-archive/*/src /app/src
          mv /tmp/src-archive/*/pyproject.toml /app/pyproject.toml
          rm -rf /tmp/src-archive
      fi
      cd /app
      python3.11 -m venv .venv
      source .venv/bin/activate
      pip3.11 install --upgrade pip wheel setuptools uv
      pip3 install docling==2.108.0 --extra-index-url https://download.pytorch.org/whl/cpu
      uv pip install -e ".[all]" &
      INSTALL_PID=$!

      # Install Models
      if ${install_ollama}; then
        echo "Pulling Ollama Models"
        ollama pull granite4.1:8b > /dev/null 2>&1
        ollama pull mxbai-embed-large > /dev/null 2>&1
      fi

      # Wait for python modules to finish
      wait $INSTALL_PID

      # Create .env.vm for pydantic settings
      cat > /app/src/.env.vm << 'ENVEOF'
      ## AI Optimizer VM Environment (Version: ${app_version})
      AIO_DB_USERNAME=AI_OPTIMIZER
      AIO_DB_PASSWORD=${db_password}
      AIO_DB_DSN=${db_service}
      AIO_OCI_CLI_AUTH=instance_principal
      AIO_CLIENT_ADDRESS=0.0.0.0
      AIO_CLIENT_COOKIE_SECRET=${client_cookie_secret}
      AIO_SERVER_ADDRESS=0.0.0.0
      %{~ if db_type == "ADB" }
      AIO_DB_WALLET_PASSWORD=${db_password}
      %{~ endif }
      %{~ if install_ollama }
      AIO_ON_PREM_OLLAMA_URL=http://127.0.0.1:11434
      %{~ endif }
      %{~ if object_storage_bucket != "" }
      AIO_OCI_SOURCE_BUCKET_COMPARTMENT_ID=${compartment_id}
      AIO_OCI_SOURCE_BUCKET_NAME=${object_storage_bucket}
      %{~ endif }
      ENVEOF
      chmod 640 /app/src/.env.vm

runcmd:
  - /tmp/install_packages.sh policycoreutils-python-utils python3.11 jdk-26-headless sqlcl zstd mesa-libGL
  - /tmp/root_setup.sh
  - su - oracleai -c '/tmp/app_setup.sh'
  - semanage fcontext -a -t bin_t "/app(/.*)?"
  - restorecon -RF /app
  - systemctl daemon-reexec
  - systemctl daemon-reload
  - systemctl enable ai-optimizer.service
  - systemctl start ai-optimizer.service
  - rm /tmp/app_setup.sh /tmp/root_setup.sh