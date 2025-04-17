# Install Oracle DB23ai

<!-- spell-checker:ignore streamlit, venv -->

## Description

AI Vector Search in Oracle Database 23ai provides the ability to store and query private business data using a natural language interface. The **AI Optimizer** uses these capabilities to provide more accurate and relevant LLM responses via Retrieval-Augmented Generation (**RAG**). [Oracle Database 23ai Free](https://www.oracle.com/uk/database/free/get-started) provides an ideal, no-cost vector store for this walkthrough.

---

⚠️ **Warning**

If you are running this lab on a MacOS system, you would need to simulate podman using colima. Run this command to start colima with profile x86:

```bash
alias podman=docker 
colima start x86
```

---

To start Oracle Database 23ai Free:

1. Start the container:

```bash
podman run -d --name db23ai -p 1521:1521 container-registry.oracle.com/database/free:23.7.0.0-amd64
```

2. Alter the vector_memory_size parameter and create a new database user:

```bash
podman exec -it db23ai sqlplus '/ as sysdba'
```

```bash
alter system set vector_memory_size=512M scope=spfile;

alter session set container=FREEPDB1;

CREATE USER "VECTOR" IDENTIFIED BY vector
    DEFAULT TABLESPACE "USERS"
    TEMPORARY TABLESPACE "TEMP";
GRANT "DB_DEVELOPER_ROLE" TO "VECTOR";
ALTER USER "VECTOR" DEFAULT ROLE ALL;
ALTER USER "VECTOR" QUOTA UNLIMITED ON USERS;
EXIT;
```

3. Bounce the database for the vector_memory_size to take effect:

```bash
podman container restart db23ai
```

In the next steps of this lab, you will need to check the items inside your database 23ai. In order to do so, install the VS Code **SQL Developer** plugin:

![sql-developer-plugin](images/sql-developer-plugin.png)