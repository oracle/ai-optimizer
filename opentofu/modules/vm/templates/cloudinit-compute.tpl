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
      if [ ${install_ollama} ]; then
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
      # Setup for Instance Principles
      export OCI_CLI_AUTH=instance_principal

      # Download/Setup Source Code
      curl -s https://api.github.com/repos/oracle-samples/ai-optimizer/releases/latest \
      | grep tarball_url \
      | cut -d '"' -f 4 \
      | xargs curl -L -o /tmp/source.tar.gz
      tar zxf /tmp/source.tar.gz --strip-components=2 -C /app '*/src'
      cd /app
      python3.11 -m venv .venv
      source .venv/bin/activate
      pip3.11 install --upgrade pip wheel setuptools
      pip3.11 install -e ".[all]" --quiet --no-input &
      INSTALL_PID=$!

      # Wait for Database and Download Wallet
      while [ $SECONDS -lt $((SECONDS + 600)) ]; do
        echo "Waiting for Database... ${db_name}"
        ID=$(oci db autonomous-database list --compartment-id ${compartment_id} --display-name ${db_name} \
          --lifecycle-state AVAILABLE --query 'data[0].id' --raw-output)
        if [ -n "$ID" ]; then
          echo "Database Found; Downloading Wallet for $ID..."
          oci db autonomous-database generate-wallet --autonomous-database-id $ID --password '${db_password}' --file /tmp/wallet.zip
          break
        fi
        sleep 15
      done
      mkdir -p /app/tns_admin
      unzip -o /tmp/wallet.zip -d /app/tns_admin

      # Install Models
      if [ ${install_ollama} ]; then
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
      export DB_USERNAME='ADMIN'
      export DB_PASSWORD='${db_password}'
      export DB_DSN='${db_name}_TP'
      export DB_WALLET_PASSWORD='${db_password}'
      if [ ${install_ollama} ]; then
        export ON_PREM_OLLAMA_URL=http://127.0.0.1:11434
      fi
      # Clean Cache
      find /app -type d -name "__pycache__" -exec rm -rf {} \;
      find /app -type d -name ".numba_cache" -exec rm -rf {} \;
      find /app -name "*.nbc" -delete
      # Set venv and start
      source /app/.venv/bin/activate
      streamlit run /app/launch_client.py --server.port 8501 --server.address 0.0.0.0

runcmd:
  - /tmp/root_setup.sh
  - su - oracleai -c '/tmp/app_setup.sh'
  - rm /tmp/app_setup.sh /tmp/root_setup.sh /tmp/source.tar.gz /tmp/wallet.zip
  - chown oracleai:oracleai /app/start.sh
  - systemctl daemon-reexec
  - systemctl daemon-reload
  - systemctl enable ai-optimizer.service
  - systemctl start ai-optimizer.service