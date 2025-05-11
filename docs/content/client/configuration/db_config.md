+++
title = "🗄️ Database Configuration"
weight = 20
+++

<!--
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore tablespace mycomplexsecret mycomplexwalletsecret 
-->

To use the Retrieval-Augmented Generation (RAG) functionality of the {{< short_app_ref >}}, you will need to setup/enable an [embedding model](../model_config) and have access to an **Oracle Database 23ai**. Both the [Always Free Oracle Autonomous Database Serverless (ADB-S)](https://docs.oracle.com/en/cloud/paas/autonomous-database/serverless/adbsb/autonomous-always-free.html) and the [Oracle Database 23ai Free](https://www.oracle.com/uk/database/free/get-started/) are supported. They are a great, no-cost, way to get up and running quickly.

## Configuration

The database can either be configured through the [{{< short_app_ref >}} interface](#-short_app_ref--interface) or by using [environment variables](#environment-variables).

### {{< short_app_ref >}} Interface

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

## Using a Wallet/TNS_ADMIN Directory

For mTLS database connectivity or, if you prefer to specify a TNS alias instead of a full connect string, you can use the contents of a `TNS_ADMIN` directory.

{{% notice style="default" title="Great things come from unzipped files." icon="circle-info" %}}
If using and ADB-S wallet, unzip the contents into the `TNS_ADMIN` directory. The `.zip` file will not be recognized.
{{% /notice %}}


### Bare-Metal Installation

For bare-metal installations, set the `TNS_ADMIN` environment variable, or copy the contents of your current TNS_ADMIN to `src/tns_admin` before starting the {{< short_app_ref >}}.

### Container Installation

For container installations, there are a couple of ways to include the contents of your `TNS_ADMIN` in the image:

- Before building the image, copy the contents of your `TNS_ADMIN` to `src/tns_admin`. This will include your `TNS_ADMIN` as part of the image build.
- Mount your `TNS_ADMIN` directory into the container on startup, for example: `podman run -p 8501:8501 -v $TNS_ADMIN:/tns_admin -it --rm ai-optimizer-server`
- Copy the `TNS_ADMIN` directory into an existing running container, for example: `podman cp $TNS_ADMIN /app/tns_admin ai-optimizer-server`

## Database User

A database user is required to store the embeddings, used for **RAG**, into the Oracle Database. A non-privileged user with a *non-SYSTEM tablespace* should be used for this purpose.  Use the below syntax as an __example__ of creating a new user with least privileges:

```sql
CREATE USER "DEMO" IDENTIFIED BY MYCOMPLEXSECRET
    DEFAULT TABLESPACE "DATA"
    TEMPORARY TABLESPACE "TEMP";
GRANT "DB_DEVELOPER_ROLE" TO "DEMO";
ALTER USER "DEMO" DEFAULT ROLE ALL;
ALTER USER "DEMO" QUOTA UNLIMITED ON DATA;
```

If running on a supported database for [SelectAI](https://docs.oracle.com/en-us/iaas/autonomous-database-serverless/doc/select-ai.html) and want to use the feature, grant the following additional privileges and open appropriate ACLs:

```sql
GRANT EXECUTE ON DBMS_CLOUD TO DEMO;
GRANT EXECUTE ON DBMS_CLOUD_AI TO DEMO;
GRANT EXECUTE ON DBMS_CLOUD_PIPELINE TO DEMO;
```

{{% notice style="default" title="One schema fits none..." icon="circle-info" %}}
Creating multiple users in the same database allows developers to separate their experiments simply by changing the "Database User"
{{% /notice %}}
