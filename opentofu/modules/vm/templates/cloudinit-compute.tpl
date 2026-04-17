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
packages:
  - python3.11
  - jdk-26-headless
  - sqlcl
  - zstd

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
      if [ "${optimizer_version}" = "Stable" ]; then
          echo "Downloading Code from LATEST release"
          curl -L "https://github.com/oracle/ai-optimizer/releases/latest/download/ai-optimizer-src.tar.gz" \
            | tar -xz -C /app
      else
          echo "Downloading Code from branch: ${optimizer_branch}"
          mkdir -p /tmp/src-archive
          curl -L "https://github.com/oracle/ai-optimizer/archive/refs/heads/${optimizer_branch}.tar.gz" \
            | tar -xz -C /tmp/src-archive
          mv /tmp/src-archive/*/src /app/src
          mv /tmp/src-archive/*/pyproject.toml /app/pyproject.toml
          rm -rf /tmp/src-archive
      fi
      cd /app
      python3.11 -m venv .venv
      source .venv/bin/activate
      pip3.11 install --upgrade pip wheel setuptools uv
      pip3 install docling==2.80.0 --extra-index-url https://download.pytorch.org/whl/cpu
      uv pip install -e ".[all]" &
      INSTALL_PID=$!

      # Install Models
      if ${install_ollama}; then
        echo "Pulling Ollama Models"
        ollama pull qwen3:8b > /dev/null 2>&1
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
      %{~ if db_type == "ADB" }
      AIO_DB_WALLET_PASSWORD=${db_password}
      %{~ endif }
      %{~ if install_ollama }
      AIO_ON_PREM_OLLAMA_URL=http://127.0.0.1:11434
      %{~ endif }
      ENVEOF
      chmod 640 /app/src/.env.vm

runcmd:
  - /tmp/root_setup.sh
  - su - oracleai -c '/tmp/app_setup.sh'
  - semanage fcontext -a -t bin_t "/app(/.*)?"                                                                                                              
  - restorecon -RF /app  
  - systemctl daemon-reexec
  - systemctl daemon-reload
  - systemctl enable ai-optimizer.service
  - systemctl start ai-optimizer.service
  - rm /tmp/app_setup.sh /tmp/root_setup.sh