#cloud-config
# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
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

write_files:
  - path: /etc/systemd/system/ai-optimizer.service
    permissions: '0644'
    content: |
      [Unit]
      Description=Run app start script
      After=network.target

      [Service]
      Type=simple
      ExecStart=/bin/bash /app/start.sh
      User=oracleai
      Group=oracleai
      WorkingDirectory=/app
      Environment="HOME=/app"
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
      if [ "${optimizer_version}" = "Experimental" ]; then
          URL="https://github.com/oracle/ai-optimizer/archive/refs/heads/main.tar.gz"
          curl -L "$URL" | tar -xz -C /app \
            --strip-components=2 ai-optimizer-main/src \
            --strip-components=1 ai-optimizer-main/pyproject.toml
      else
          URL="https://github.com/oracle/ai-optimizer/releases/latest/download/ai-optimizer-src.tar.gz"
          curl -L "$URL" | tar -xz -C /app
      fi
      cd /app
      python3.11 -m venv .venv
      source .venv/bin/activate
      pip3.11 install --upgrade pip wheel setuptools uv
      uv pip install torch==2.9.0+cpu -f https://download.pytorch.org/whl/cpu/torch
      uv pip install -e ".[all]" &
      INSTALL_PID=$!

      # Install Models
      if ${install_ollama}; then
        echo "Pulling Ollama Models"
        ollama pull llama3.1 > /dev/null 2>&1
        ollama pull mxbai-embed-large > /dev/null 2>&1
      fi

      # Wait for python modules to finish
      wait $INSTALL_PID

  - path: /app/start.sh
    permissions: '0750'
    content: |
      #!/bin/bash
      export OCI_CLI_AUTH=instance_principal
      export API_SERVER_CONTROL="True"
      export TNS_ADMIN='/app/tns_admin'
      export DB_USERNAME='AI_OPTIMIZER'
      export DB_PASSWORD='${db_password}'
      export DB_DSN='${db_service}'
      if [ ${db_type} == "ADB" ]; then
        export DB_WALLET_PASSWORD='${db_password}'
      fi

      if ${install_ollama}; then
        export ON_PREM_OLLAMA_URL=http://127.0.0.1:11434
      fi
      # Clean Cache
      find /app -type d -name "__pycache__" -exec rm -rf {} \;
      find /app -type d -name ".numba_cache" -exec rm -rf {} \;
      find /app -name "*.nbc" -delete
      # Set venv and start
      source /app/.venv/bin/activate
      streamlit run /app/src/launch_client.py --server.port 8501 --server.address 0.0.0.0

runcmd:
  - /tmp/root_setup.sh
  - su - oracleai -c '/tmp/app_setup.sh'
  - chown oracleai:oracleai /app/start.sh
  - systemctl daemon-reexec
  - systemctl daemon-reload
  - systemctl enable ai-optimizer.service
  - systemctl start ai-optimizer.service
  - rm /tmp/app_setup.sh /tmp/root_setup.sh