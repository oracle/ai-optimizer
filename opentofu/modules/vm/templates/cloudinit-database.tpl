#cloud-config
# Copyright (c) 2024, 2026, Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
# spell-checker: disable

package_update: false
# Packages are installed via /tmp/install_packages.sh (provided by the
# compute template, see cloudinit-compute.tpl). Cloud-config's `packages:`
# fires before the OCI VCN resolver is reliably ready.

write_files:
  - path: /tmp/db_priv_sql.sh
    permissions: '0755'
    content: |
      export API_SERVER_HOST=$(hostname -f)
      export DB_DBA_USER='${db_dba_user}'
      export AIO_DB_USERNAME='AI_OPTIMIZER'
      export AIO_DB_PASSWORD='${db_password}'
      export AIO_DB_DSN='${db_service}'

      echo "Starting Database Configuration"
      sql /nolog <<EOF
      WHENEVER SQLERROR EXIT 1
      WHENEVER OSERROR EXIT 1
      set cloudconfig /app/tns_admin/wallet.zip
      connect $DB_DBA_USER/$AIO_DB_PASSWORD@$AIO_DB_DSN
      DECLARE
        l_conn_user VARCHAR2(255);
        l_user      VARCHAR2(255);
        l_tblspace  VARCHAR2(255);
        package_missing EXCEPTION;
        PRAGMA EXCEPTION_INIT(package_missing, -4042);
      BEGIN
        BEGIN
            SELECT user INTO l_conn_user FROM DUAL;
            SELECT username INTO l_user FROM DBA_USERS WHERE USERNAME='$AIO_DB_USERNAME';
        EXCEPTION WHEN no_data_found THEN
            EXECUTE IMMEDIATE 'CREATE USER "$AIO_DB_USERNAME" IDENTIFIED BY "$AIO_DB_PASSWORD"';
        END;
        SELECT default_tablespace INTO l_tblspace FROM dba_users WHERE username = '$AIO_DB_USERNAME';
        EXECUTE IMMEDIATE 'ALTER USER "$AIO_DB_USERNAME" QUOTA UNLIMITED ON ' || l_tblspace;
        EXECUTE IMMEDIATE 'GRANT DB_DEVELOPER_ROLE TO "$AIO_DB_USERNAME"';
        BEGIN
          EXECUTE IMMEDIATE 'GRANT EXECUTE ON DBMS_CLOUD_AI TO "$AIO_DB_USERNAME"';
          EXECUTE IMMEDIATE 'GRANT EXECUTE ON DBMS_CLOUD_PIPELINE TO "$AIO_DB_USERNAME"';
        EXCEPTION WHEN package_missing THEN
          DBMS_OUTPUT.PUT_LINE('DBMS_CLOUD Packages do not exist, skipping grants.');
        END;
        EXECUTE IMMEDIATE 'ALTER USER "$AIO_DB_USERNAME" DEFAULT ROLE ALL';
      END;
      /
      -- Deep Data Security privileges (Oracle AI Database 26ai). Applied independently and tolerant
      -- of failure, so provisioning continues unchanged on databases that do not support Deep Data
      -- Security (each unsupported grant errors and is skipped). AIO_DDS_ROLE is a standard role
      -- carrying CREATE SESSION: the app grants it to local data roles at creation, so end users
      -- assigned those data roles can connect (connect-as). CREATE ROLE re-runs error harmlessly.
      BEGIN
        FOR g IN (SELECT column_value AS stmt FROM TABLE(sys.odcivarchar2list(
          'GRANT CREATE DATA ROLE TO "$AIO_DB_USERNAME"',
          'GRANT DROP DATA ROLE TO "$AIO_DB_USERNAME"',
          'GRANT CREATE END USER TO "$AIO_DB_USERNAME"',
          'GRANT DROP END USER TO "$AIO_DB_USERNAME"',
          'GRANT CREATE DATA GRANT TO "$AIO_DB_USERNAME"',
          'GRANT ADMINISTER ANY DATA GRANT TO "$AIO_DB_USERNAME"',
          'GRANT CREATE END USER CONTEXT TO "$AIO_DB_USERNAME"',
          'GRANT CREATE END USER SECURITY CONTEXT TO "$AIO_DB_USERNAME"',
          'GRANT SELECT ON DBA_DATA_ROLES TO "$AIO_DB_USERNAME"',
          'GRANT SELECT ON DBA_DATA_ROLE_GRANTS TO "$AIO_DB_USERNAME"',
          'GRANT SELECT ON DBA_END_USERS TO "$AIO_DB_USERNAME"',
          'CREATE ROLE AIO_DDS_ROLE',
          'GRANT CREATE SESSION TO AIO_DDS_ROLE',
          'GRANT AIO_DDS_ROLE TO "$AIO_DB_USERNAME" WITH ADMIN OPTION',
          'GRANT GRANT ANY DATA ROLE TO "$AIO_DB_USERNAME"'
        ))) LOOP
          BEGIN
            EXECUTE IMMEDIATE g.stmt;
          EXCEPTION WHEN OTHERS THEN
            DBMS_OUTPUT.PUT_LINE('Skipping (Deep Data Security unavailable?): ' || g.stmt || ' -> ' || SQLERRM);
          END;
        END LOOP;
      END;
      /
      BEGIN
        DBMS_NETWORK_ACL_ADMIN.APPEND_HOST_ACE(
          host => '$API_SERVER_HOST',
          ace  => xs\$ace_type(
            privilege_list => xs\$name_list('http', 'connect', 'resolve'),
            principal_name => '$AIO_DB_USERNAME',
            principal_type => xs_acl.ptype_db
          )
        );
      END;
      /
      EOF

  - path: /tmp/db_setup.sh
    permissions: '0755'
    content: |
      #!/bin/bash

      if [ ${db_type} == "ADB" ]; then
        export OCI_CLI_AUTH=instance_principal
        mkdir -p /app/tns_admin
        # Wait for Database and Download Wallet
        echo "Downloading ADB Wallet..."
        max_attempts=40
        attempt=1
        while [ $attempt -le $max_attempts ]; do
          echo "Waiting for Database... ${db_name}"
          ID=$(oci db autonomous-database list --compartment-id ${compartment_id} --display-name ${db_name} \
            --lifecycle-state AVAILABLE --query 'data[0].id' --raw-output)
          if [ -n "$ID" ]; then
            echo "Database Found; Downloading Wallet for $ID..."
            oci db autonomous-database generate-wallet --autonomous-database-id $ID --password '${db_password}' --file /app/tns_admin/wallet.zip
            break
          fi
          sleep 15
          ((attempt++))
        done
        unzip -o /app/tns_admin/wallet.zip -d /app/tns_admin
      else
        echo "Database is not ADB... skipping."
      fi

runcmd:
  - /tmp/install_packages.sh policycoreutils-python-utils python39-oci-cli jdk-26-headless sqlcl
  - su - oracleai -c '/tmp/db_setup.sh'
  - su - oracleai -c '/tmp/db_priv_sql.sh'
  - rm /tmp/db_setup.sh /tmp/db_priv_sql.sh /tmp/install_packages.sh
