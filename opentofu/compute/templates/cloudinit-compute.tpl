#cloud-config

package_update: false
packages:
  - git
  - python3.11
  - python36-oci-cli

users:
  - name: oracleai
    uid: 10001
    gid: 10001
    shell: /bin/bash
    homedir: /app

write_files:
  - path: /home/opc/firewall.sh
    permissions: '0755'
    content: |
      #!/bin/env bash
      systemctl stop firewalld.service
      firewall-offline-cmd --zone=public --add-port 8501/tcp
      systemctl start firewalld.service
    append: false
    defer: false
  - path: /tmp/setup.sh
    permissions: '0755'
    content: |
      #!/bin/bash
      mkdir -p /app/.oci
      echo -e '[DEFAULT]\ninstance_principle=true\nregion=${oci_region}' > /app/.oci/config
      oci setup repair-file-permissions --file /app/.oci/config
      curl -L -o /tmp/source.tar.gz https://github.com/oracle-samples/ai-explorer/archive/refs/heads/main.tar.gz
      tar zxf /tmp/source.tar.gz --strip-components=2 -C /app '*/src'
      cd /app
      python3.11 -m venv .venv
      source .venv/bin/activate
      pip3.11 install --upgrade pip wheel setuptools
      pip3.11 install torch==2.6.0+cpu -f https://download.pytorch.org/whl/cpu/torch
      pip3.11 install -e ".[all]" --quiet --no-input &
      INSTALL_PID=$!
      oci db autonomous-database generate-wallet --autonomous-database-id "${adb_ocid}" --password "${db_password}" --file /tmp/wallet.zip --auth instance_principal
      mkdir -p /app/tns_admin
      unzip -o /tmp/wallet.zip -d /app/tns_admin
      export DB_USERNAME="ADMIN"
      export DB_PASSWORD="${db_password}"
      export DB_DSN="${db_name}_TP"
      export DB_WALLET_PASSWORD="${db_password}"
      wait $INSTALL_PID
      nohup streamlit run launch_client.py --server.port 8501 --server.address 0.0.0.0 &
    append: false
    defer: false

runcmd:
  - su - oracleai -c '/tmp/setup.sh'
  - /home/opc/firewall.sh