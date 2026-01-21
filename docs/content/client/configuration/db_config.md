+++
title = "🗄️ Database Configuration"
weight = 20
+++

<!--
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore tablespace mycomplexsecret mycomplexwalletsecret 
-->

To use the Retrieval-Augmented Generation (RAG) functionality of the {{< short_app_ref >}}, you will need to setup/enable an [embedding model](../model_config) and have access to an **Oracle AI Database**. Both the [Always Free Oracle Autonomous Database Serverless (ADB-S)](https://docs.oracle.com/en/cloud/paas/autonomous-database/serverless/adbsb/autonomous-always-free.html) and the [Oracle AI Database Free](https://www.oracle.com/database/free/get-started/) are supported. They are a great, no-cost, way to get up and running quickly.

## Configuration

The database can either be configured through the [{{< short_app_ref >}} interface](#-short_app_ref--interface) or by using [environment variables](#environment-variables).

---

### Interface

To configure the Database from the {{< short_app_ref >}}, navigate to `Configuration -> Database`:

![Database Config](../images/database_config.png)

Provide the following input:

- **DB Username**: The pre-created [database username](#database-user) where the embeddings will be stored
- **DB Password**: The password for the **DB Username**
- **Database Connect String**: The full connection string or [TNS Alias](#using-a-wallettns_admin-directory) for the Database. 
    This is normally in the form of 
    `
    (DESCRIPTION=(ADDRESS=(PROTOCOL=tcp)(HOST=<hostname>)(PORT=<port>))(CONNECT_DATA=(SERVICE_NAME=<service_name>)))
    ` 
    or 
    `
    //<hostname>:<port>/<service_name>
    `
- **Wallet Password** (_Optional_): If the connection to the database uses mTLS, provide the wallet password. {{< icon "star" >}}Review [Using a Wallet](#using-a-wallettns_admin-directory) for additional setup instructions.

Once all fields are set, click the `Save` button.

---

### Environment Variables

The following environment variables can be set, prior to starting the {{< short_app_ref >}}, to automatically configure the database:

- **DB_USERNAME**: The pre-created [database username](#database-user) where the embeddings will be stored
- **DB_PASSWORD**: The password for the `DB Username`
- **DB_DSN**: The connection string or [TNS Alias](#using-a-wallettns_admin-directory) for the Database. This is normally in the form of `(description=... (service_name=<service_name>))` or `//host:port/service_name`.
- **DB_WALLET_PASSWORD** (_Optional_): If the connection to the database uses mTLS, provide the wallet password. {{< icon "star" >}}Review [Using a Wallet](#using-a-wallettns_admin-directory) for additional setup instructions.

For Example:

```bash
export DB_USERNAME="DEMO"
export DB_PASSWORD=MYCOMPLEXSECRET
export DB_DSN="//localhost:1521/OPTIMIZER"
export DB_WALLET_PASSWORD=MYCOMPLEXWALLETSECRET
```

--- 

## Using a Wallet/TNS_ADMIN Directory

For mTLS database connectivity or, if you prefer to specify a TNS alias instead of a full connect string, you can use the contents of a `TNS_ADMIN` directory.

{{% notice style="default" title="Great things come from unzipped files." icon="circle-info" %}}
If using and ADB-S wallet, unzip the contents into the `TNS_ADMIN` directory. The `.zip` file will not be recognized.
{{% /notice %}}


### Bare-Metal

For bare-metal installations, set the `TNS_ADMIN` environment variable to the location of your unzipped wallet files before starting the {{< short_app_ref >}}.

### Container

When starting the container, volume mount the configuration file to `/app/tns_admin` for it to be used.  

For example:
```bash
podman run -v $TNS_ADMIN$:/app/tns_admin -p 8501:8501 -it --rm ai-optimizer-aio
```

---

## Database User

A database user is required to store the embeddings, used for **RAG**, into the Oracle Database. A non-privileged user with a *non-SYSTEM tablespace* should be used for this purpose.  Use the below syntax as an __example__ of creating a new user with least privileges (change the value of `c_user_password`):

```sql
DECLARE
    c_user_password dba_users.password%TYPE := 'MYSUPERSECRET';
    v_default_perm  database_properties.property_value%TYPE;
    v_default_temp  database_properties.property_value%TYPE;
    v_sql           VARCHAR2(500);
BEGIN    
    -- Get default permanent tablespace
    SELECT property_value 
      INTO v_default_perm
      FROM database_properties 
     WHERE property_name = 'DEFAULT_PERMANENT_TABLESPACE';

    -- Get default temporary tablespace
    SELECT property_value 
      INTO v_default_temp
      FROM database_properties 
     WHERE property_name = 'DEFAULT_TEMP_TABLESPACE';

    -- Build dynamic CREATE USER statement
    v_sql := 'CREATE USER demo IDENTIFIED BY "' || c_user_password || '" ' ||
             'DEFAULT TABLESPACE ' || v_default_perm || ' ' ||
             'TEMPORARY TABLESPACE ' || v_default_temp;
    EXECUTE IMMEDIATE v_sql;
END;
/
GRANT "DB_DEVELOPER_ROLE" TO "DEMO";
ALTER USER "DEMO" DEFAULT ROLE ALL;
ALTER USER "DEMO" QUOTA UNLIMITED ON DATA;
```

{{% notice style="default" title="One schema fits none..." icon="circle-info" %}}
Creating multiple users in the same database allows developers to separate their experiments simply by changing the "Database User"
{{% /notice %}}
