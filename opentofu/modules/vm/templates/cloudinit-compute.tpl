#cloud-config
# Copyright (c) 2024, 2025, Oracle and/or its affiliates.
# All rights reserved. The Universal Permissive License (UPL), Version 1.0 as shown at http://oss.oracle.com/licenses/upl
# spell-checker: disable

package_update: false
packages:
  - git
  - python3.11

users:
  - name: oracleai
    uid: 10001
    gid: 10001
    shell: /bin/bash
    homedir: /app

write_files:
  - path: /tmp/root_setup.sh
    permissions: '0755'
    content: |
      #!/bin/env bash
      curl -fsSL https://ollama.com/install.sh | sh
      systemctl enable ollama
      systemctl daemon-reload
      systemctl restart ollama
      systemctl stop firewalld.service
      firewall-offline-cmd --zone=public --add-port 8501/tcp
      firewall-offline-cmd --zone=public --add-port 8000/tcp
      systemctl start firewalld.service
    append: false
    defer: false
  - path: /tmp/app_setup.sh
    permissions: '0755'
    content: |
      #!/bin/bash
      # Setup for Instance Principles
      export OCI_CLI_AUTH=instance_principal

      # Setup oci config.ini to indicate to app to use instance_principal
      # mkdir -p /app/.oci
      # echo -e '[DEFAULT]\nregion=${oci_region}\ntenancy=${tenancy_id}' > /app/.oci/config
      # oci setup repair-file-permissions --file /app/.oci/config

      # Download/Setup Source Code
      curl -L -o /tmp/source.tar.gz ${source_code}.tar.gz
      tar zxf /tmp/source.tar.gz --strip-components=2 -C /app '*/src'
      cd /app
      python3.11 -m venv .venv
      source .venv/bin/activate
      pip3.11 install --upgrade pip wheel setuptools oci-cli
      pip3.11 install torch==2.6.0+cpu -f https://download.pytorch.org/whl/cpu/torch
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
      ollama pull llama3.1
      ollama pull mxbai-embed-large

      # Wait for python modules to finish
      wait $INSTALL_PID

      # Startup application
      export DB_USERNAME='ADMIN'
      export DB_PASSWORD='${db_password}'
      export DB_DSN='${db_name}_TP'
      export DB_WALLET_PASSWORD='${db_password}'
      export ON_PREM_OLLAMA_URL=http://127.0.0.1:11434
      export LOG_LEVEL=DEBUG
      nohup streamlit run launch_client.py --server.port 8501 --server.address 0.0.0.0 &
    append: false
    defer: false

runcmd:
  - /tmp/root_setup.sh
  - su - oracleai -c '/tmp/app_setup.sh'
  - rm /tmp/app_setup.sh /tmp/root_setup.sh /tmp/source.tar.gz /tmp/wallet.zip