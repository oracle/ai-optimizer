+++
title = "🗄️ Database Configuration"
weight = 20
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore enquote mysupersecret tablespace varchar relref
-->

To use the Retrieval-Augmented Generation (**RAG**) and Natural Language to SQL (**NL2SQL**) functionality of the {{% short_app_ref %}}, you will need access to an **Oracle AI Database**. Both the [Always Free Oracle Autonomous Database Serverless (ADB-S)](https://docs.oracle.com/en/cloud/paas/autonomous-database/serverless/adbsb/autonomous-always-free.html) and the [Oracle AI Database Free](https://www.oracle.com/database/free/get-started/) are supported. They are a great, no-cost, way to get up and running quickly.

## Configuration

The database can either be configured through the [{{% short_app_ref %}} interface](#-short_app_ref--interface) or by using [environment variables](#environment-variables).

---

### Interface

To configure the Database from the {{% short_app_ref %}}, navigate to `Configuration -> Database`:

![Database Config](../images/database_config.png)

#### CORE Database

The first database configured must use the alias **CORE**. The **CORE** database is used for application persistence (settings, test sets, evaluations). When no database has been configured, the alias field will automatically be set to `CORE` and cannot be changed.

#### Additional Databases

Once the **CORE** database is configured, additional databases can be added with custom aliases by selecting **Add New...** from the database dropdown. These databases can be used for Vector Search and NL2SQL operations.

![Database Add New](../images/database_add_new.png)

#### Input Fields

Provide the following input:

- **Alias**: A unique identifier for the database configuration (automatically set to `CORE` for the first database)
- **Username**: The pre-created [database username](#database-user) where the embeddings will be stored
- **Password**: The password for the **Username**
- **DSN (Connect String)**: The full connection string or [TNS Alias](#using-a-wallettns_admin-directory) for the Database.
    This is normally in the form of
    `
    (DESCRIPTION=(ADDRESS=(PROTOCOL=tcp)(HOST=<hostname>)(PORT=<port>))(CONNECT_DATA=(SERVICE_NAME=<serviceName>)))
    `
    or
    `
    //<hostname>:<port>/<serviceName>
    `
- **Wallet Password** (_Optional_): If the connection to the database uses mTLS, provide the wallet password. {{< icon "star" >}}Review [Using a Wallet](#using-a-wallettns_admin-directory) for additional setup instructions.

Once all fields are set, click the `Create` or `Save` button.

---

### Environment Variables

The database can also be configured using environment variables. See [Database]({{% relref "/configuration#database" %}}) under Environment Variables.

---

## Using a Wallet/TNS_ADMIN Directory

For mTLS database connectivity or, if you prefer to specify a TNS alias instead of a full connect string, you can use the contents of a `TNS_ADMIN` directory.

{{% notice style="default" title="Great things come from unzipped files." icon="circle-info" %}}
If using and ADB-S wallet, unzip the contents into the `TNS_ADMIN` directory. The `.zip` file will not be recognized.
{{% /notice %}}


### Bare-Metal

For bare-metal installations, set the `TNS_ADMIN` environment variable to the location of your unzipped wallet files before starting the {{% short_app_ref %}}.

### Container

When starting the container, volume mount the configuration file to `/app/tns_admin` for it to be used.

For example:
```bash
podman run -v $TNS_ADMIN:/app/tns_admin -p 8501:8501 -it --rm ai-optimizer-aio
```

---

## Database User

For both **RAG** and **NL2SQL** the {{% short_app_ref %}} will need to authenticate to an Oracle AI Database.  AI agents will use this user to retrieve data,
so it’s important to *carefully consider* the level of access granted to it.
At a minimum, a non-privileged user with a *non-SYSTEM tablespace* should be used for this purpose.

Use the below syntax as an __example__ of creating a new user with least privileges (change the value of `c_user_password`):

```sql
DECLARE
    c_user_name     CONSTANT VARCHAR2(30) := 'DEMO';
    c_user_password dba_users.password%TYPE := 'MYSUPERSECRET';
    v_default_perm  database_properties.property_value%TYPE;
    v_default_temp  database_properties.property_value%TYPE;
    v_sql           VARCHAR2(500);
BEGIN
    SELECT property_value
    INTO v_default_perm
    FROM database_properties
    WHERE property_name = 'DEFAULT_PERMANENT_TABLESPACE';

    SELECT property_value
    INTO v_default_temp
    FROM database_properties
    WHERE property_name = 'DEFAULT_TEMP_TABLESPACE';

    v_sql := 'CREATE USER ' || DBMS_ASSERT.ENQUOTE_NAME(c_user_name, FALSE) ||
            ' IDENTIFIED BY "' || c_user_password || '" ' ||
            'DEFAULT TABLESPACE ' || v_default_perm || ' ' ||
            'TEMPORARY TABLESPACE ' || v_default_temp;
    EXECUTE IMMEDIATE v_sql;

    EXECUTE IMMEDIATE 'GRANT DB_DEVELOPER_ROLE TO ' ||
        DBMS_ASSERT.ENQUOTE_NAME(c_user_name, FALSE);
    EXECUTE IMMEDIATE 'ALTER USER ' ||
        DBMS_ASSERT.ENQUOTE_NAME(c_user_name, FALSE) || ' DEFAULT ROLE ALL';
    EXECUTE IMMEDIATE 'ALTER USER ' ||
        DBMS_ASSERT.ENQUOTE_NAME(c_user_name, FALSE) || ' QUOTA UNLIMITED ON DATA';
END;
/
```

{{% notice style="default" title="One schema fits none..." icon="circle-info" %}}
Creating multiple users in the same database allows developers to separate their experiments simply by changing the "Database User"
{{% /notice %}}

## Deep Data Security Privileges

To use the [Deep Data Security]({{% relref "/client/tools/deepsec" %}}) tool, the database user needs the additional privileges below. They are optional: when they are absent — or when the database does not support Deep Data Security — the tool is automatically disabled in the GUI.

```sql
GRANT CREATE DATA ROLE TO "DEMO";
GRANT DROP DATA ROLE TO "DEMO";
GRANT CREATE END USER TO "DEMO";
GRANT DROP END USER TO "DEMO";
GRANT CREATE DATA GRANT TO "DEMO";
GRANT CREATE END USER CONTEXT TO "DEMO";
GRANT CREATE END USER SECURITY CONTEXT TO "DEMO";
GRANT ADMINISTER ANY DATA GRANT TO "DEMO";
GRANT GRANT ANY DATA ROLE TO "DEMO";
-- Read access so the tool can list data roles and end users
GRANT SELECT ON DBA_DATA_ROLES TO "DEMO";
GRANT SELECT ON DBA_DATA_ROLE_GRANTS TO "DEMO";
GRANT SELECT ON DBA_END_USERS TO "DEMO";
```

To let **Vector Search** and **NL2SQL** connect *as* a Deep Data Security end user (the **Connect tools as** control), the end user must be able to log in. An end user cannot be granted `CREATE SESSION` directly; the privilege is carried by a standard database role that flows to the end user through a data role. As a privileged user (e.g. `ADMIN`/`SYSTEM`), create that role once and let `"DEMO"` hand it out:

```sql
-- Privileged user: one standard role that carries CREATE SESSION
CREATE ROLE AIO_DDS_ROLE;
GRANT CREATE SESSION TO AIO_DDS_ROLE;
-- Let the database user grant AIO_DDS_ROLE on (to data roles it creates) and assign data roles
GRANT AIO_DDS_ROLE TO "DEMO" WITH ADMIN OPTION;
```

The tool then grants `AIO_DDS_ROLE` to each locally-managed data role it creates, so any end user assigned that data role can be connected as.
