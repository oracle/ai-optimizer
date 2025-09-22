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
  - python36-oci-cli
  - python3.11
  - jre
  - sqlcl

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

      # Capabilities for binding to port 80
      AmbientCapabilities=CAP_NET_BIND_SERVICE
      CapabilityBoundingSet=CAP_NET_BIND_SERVICE

      # Security hardening
      NoNewPrivileges=true
      PrivateTmp=true
      ProtectSystem=full
      ProtectHome=true

      # Environment
      Environment="HOME=/app"

      # Restart policy
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
      firewall-offline-cmd --zone=public --add-port ${optimizer_client_port}/tcp
      firewall-offline-cmd --zone=public --add-port ${optimizer_server_port}/tcp
      systemctl start firewalld.service

  - path: /tmp/app_setup.sh
    permissions: '0755'
    content: |
      #!/bin/bash
      # Download/Setup Source Code
      if [ "${optimizer_version}" = "main" ]; then
          URL="https://github.com/oracle/ai-optimizer/archive/refs/heads/main.tar.gz"
          curl -L "$URL" | tar -xz -C /app --strip-components=2 ai-optimizer-main/src
      else
          URL="https://github.com/oracle/ai-optimizer/releases/latest/download/ai-optimizer-src.tar.gz"
          curl -L "$URL" | tar -xz -C /app
      fi
      cd /app
      python3.11 -m venv .venv
      source .venv/bin/activate
      pip3.11 install --upgrade pip wheel setuptools uv
      uv pip install torch==2.8.0+cpu -f https://download.pytorch.org/whl/cpu/torch
      uv pip install -e ".[all]" --quiet --prerelease=allow &
      INSTALL_PID=$!

      # Install Models
      if ${install_ollama}; then
        ollama pull llama3.1
        ollama pull mxbai-embed-large
      fi

      # Wait for python modules to finish
      wait $INSTALL_PID

  - path: /app/start.sh
    permissions: '0750'
    content: |
      #!/bin/bash
      export OCI_CLI_AUTH=instance_principal
      export API_SERVER_CONTROL='TRUE'
      export API_SERVER_PORT='${optimizer_server_port}'
      export DB_USERNAME='AI_OPTIMIZER'
      export DB_PASSWORD='${db_password}'
      export DB_DSN='${db_name}_TP'
      export DB_WALLET_PASSWORD='${db_password}'
      if ${install_ollama}; then
        export ON_PREM_OLLAMA_URL=http://127.0.0.1:11434
      fi
      # Clean Cache
      find /app -type d -name "__pycache__" -exec rm -rf {} \;
      find /app -type d -name ".numba_cache" -exec rm -rf {} \;
      find /app -name "*.nbc" -delete
      # Set venv and start
      source /app/.venv/bin/activate
      streamlit run /app/launch_client.py --server.port ${optimizer_client_port} --server.address 0.0.0.0

runcmd:
  - /tmp/root_setup.sh
  - su - oracleai -c '/tmp/app_setup.sh'
  - rm /tmp/app_setup.sh /tmp/root_setup.sh
  - chown oracleai:oracleai /app/start.sh
  - systemctl daemon-reexec
  - systemctl daemon-reload
  - systemctl enable ai-optimizer.service
  - systemctl start ai-optimizer.service