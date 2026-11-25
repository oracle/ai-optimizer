"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Raw DDL statements for Oracle AI Database schema bootstrap.
"""

# spell-checker: ignore testsets testset
RENAME_DDL = [
    """
    BEGIN
        FOR rec IN (SELECT table_name
                      FROM user_tables
                     WHERE table_name
                        IN ('OAI_TESTSETS','OAI_TESTSET_QA','OAI_EVALUATIONS')
        ) LOOP
            EXECUTE IMMEDIATE 'ALTER TABLE ' || rec.table_name ||
                ' RENAME TO ' || 'AIO_' || SUBSTR(rec.table_name, 5);
        END LOOP;
    END;
    """,
    # Replace legacy BLOB rag_report with JSON; purge old rows since the
    # column-type change makes prior payloads unreadable by current code.
    """
    DECLARE
        l_type user_tab_columns.data_type%TYPE;
    BEGIN
        SELECT data_type INTO l_type
          FROM user_tab_columns
         WHERE table_name = 'AIO_EVALUATIONS'
           AND column_name = 'RAG_REPORT';
        IF l_type = 'BLOB' THEN
            EXECUTE IMMEDIATE 'DELETE FROM aio_evaluations';
            EXECUTE IMMEDIATE 'ALTER TABLE aio_evaluations DROP COLUMN rag_report';
            EXECUTE IMMEDIATE 'ALTER TABLE aio_evaluations ADD rag_report JSON';
        END IF;
    EXCEPTION WHEN NO_DATA_FOUND THEN NULL;
    END;
    """,
    """
    DECLARE
        l_table_count      PLS_INTEGER;
        l_column_count     PLS_INTEGER;
        l_constraint_count PLS_INTEGER;

        PROCEDURE drop_constraint_if_exists(p_name VARCHAR2) IS
            l_count PLS_INTEGER;
        BEGIN
            SELECT COUNT(*) INTO l_count
              FROM user_constraints
             WHERE constraint_name = UPPER(p_name);
            IF l_count > 0 THEN
                EXECUTE IMMEDIATE 'ALTER TABLE aio_auth_authority DROP CONSTRAINT ' || p_name;
            END IF;
        END;
    BEGIN
        SELECT COUNT(*) INTO l_table_count
          FROM user_tables
         WHERE table_name = 'AIO_AUTH_AUTHORITY';

        IF l_table_count > 0 THEN
            SELECT COUNT(*) INTO l_column_count
              FROM user_tab_columns
             WHERE table_name = 'AIO_AUTH_AUTHORITY'
               AND column_name IN ('INSTALLATION_ID', 'ADMIN_DATABASE_USERNAME');

            IF l_column_count > 0 THEN
                drop_constraint_if_exists('AIO_AUTH_AUTHORITY_PK');
                drop_constraint_if_exists('AIO_AUTH_AUTHORITY_MODE_CK');

                SELECT COUNT(*) INTO l_constraint_count
                  FROM user_tab_columns
                 WHERE table_name = 'AIO_AUTH_AUTHORITY'
                   AND column_name = 'AUTHORITY_ID';
                IF l_constraint_count = 0 THEN
                    EXECUTE IMMEDIATE 'ALTER TABLE aio_auth_authority ADD authority_id NUMBER(1) DEFAULT 1';
                END IF;

                EXECUTE IMMEDIATE 'UPDATE aio_auth_authority SET authority_id = 1';
                EXECUTE IMMEDIATE
                    'UPDATE aio_auth_authority SET auth_mode = ''LOCAL_USERS'' WHERE auth_mode = ''SINGLE_USER''';
                EXECUTE IMMEDIATE 'ALTER TABLE aio_auth_authority MODIFY authority_id NOT NULL';

                SELECT COUNT(*) INTO l_constraint_count
                  FROM user_tab_columns
                 WHERE table_name = 'AIO_AUTH_AUTHORITY'
                   AND column_name = 'INSTALLATION_ID';
                IF l_constraint_count > 0 THEN
                    EXECUTE IMMEDIATE 'ALTER TABLE aio_auth_authority DROP COLUMN installation_id';
                END IF;

                SELECT COUNT(*) INTO l_constraint_count
                  FROM user_tab_columns
                 WHERE table_name = 'AIO_AUTH_AUTHORITY'
                   AND column_name = 'ADMIN_DATABASE_USERNAME';
                IF l_constraint_count > 0 THEN
                    EXECUTE IMMEDIATE 'ALTER TABLE aio_auth_authority DROP COLUMN admin_database_username';
                END IF;
            END IF;

            SELECT COUNT(*) INTO l_constraint_count
              FROM user_constraints
             WHERE constraint_name = 'AIO_AUTH_AUTHORITY_PK';
            IF l_constraint_count = 0 THEN
                EXECUTE IMMEDIATE
                    'ALTER TABLE aio_auth_authority ADD CONSTRAINT aio_auth_authority_pk PRIMARY KEY (authority_id)';
            END IF;

            SELECT COUNT(*) INTO l_constraint_count
              FROM user_constraints
             WHERE constraint_name = 'AIO_AUTH_AUTHORITY_SINGLETON_CK';
            IF l_constraint_count = 0 THEN
                EXECUTE IMMEDIATE
                    'ALTER TABLE aio_auth_authority ADD CONSTRAINT ' ||
                    'aio_auth_authority_singleton_ck CHECK (authority_id = 1)';
            END IF;

            SELECT COUNT(*) INTO l_constraint_count
              FROM user_constraints
             WHERE constraint_name = 'AIO_AUTH_AUTHORITY_MODE_CK';
            IF l_constraint_count = 0 THEN
                EXECUTE IMMEDIATE
                    'ALTER TABLE aio_auth_authority ADD CONSTRAINT aio_auth_authority_mode_ck ' ||
                    'CHECK (auth_mode IN (''LOCAL_USERS'', ''OIDC''))';
            END IF;
        END IF;
    END;
    """,
]

SCHEMA_DDL = [
    """
    CREATE TABLE IF NOT EXISTS aio_settings (
        client     VARCHAR2(255) NOT NULL,
        settings   JSON,
        created    TIMESTAMP(9) WITH LOCAL TIME ZONE,
        updated    TIMESTAMP(9) WITH LOCAL TIME ZONE,
        is_current BOOLEAN DEFAULT FALSE,
        CONSTRAINT aio_settings PRIMARY KEY (client)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS aio_testsets (
        tid     RAW(16) DEFAULT SYS_GUID(),
        name    VARCHAR2(255) NOT NULL,
        created TIMESTAMP(9) WITH LOCAL TIME ZONE,
        CONSTRAINT aio_testsets_pk PRIMARY KEY (tid),
        CONSTRAINT aio_testsets_uq UNIQUE (name, created)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS aio_testset_qa (
        tid      RAW(16) DEFAULT SYS_GUID(),
        qa_data  JSON,
        CONSTRAINT aio_testset_qa_fk FOREIGN KEY (tid)
            REFERENCES aio_testsets(tid) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS aio_evaluations (
        eid                 RAW(16) DEFAULT SYS_GUID(),
        tid                 RAW(16) DEFAULT SYS_GUID(),
        evaluated           TIMESTAMP(9) WITH LOCAL TIME ZONE,
        correctness         NUMBER DEFAULT 0,
        settings            JSON,
        rag_report          JSON,
        CONSTRAINT aio_evaluations_pk PRIMARY KEY (eid),
        CONSTRAINT aio_evaluations_fk FOREIGN KEY (tid)
            REFERENCES aio_testsets(tid) ON DELETE CASCADE,
        CONSTRAINT aio_evaluations_uq UNIQUE (eid, evaluated)
    )
    """,
    # Background split-and-embed job state. Lives in CORE so that any
    # server replica can serve GET /v1/embed/jobs/{job_id} regardless
    # of which pod accepted the POST. The pipeline body still runs on
    # the owning pod (the work directory is per-pod emptyDir), but its
    # observable state is shared. See server/app/embed/jobs.py for the
    # store / heartbeat / reaper protocol.
    """
    CREATE TABLE IF NOT EXISTS aio_embed_jobs (
        job_id      VARCHAR2(64) NOT NULL,
        client      VARCHAR2(255) NOT NULL,
        owner_pod   VARCHAR2(64) NOT NULL,
        status      VARCHAR2(16) NOT NULL,
        target_db   VARCHAR2(255) NOT NULL,
        progress    JSON,
        result      JSON,
        error       VARCHAR2(4000),
        created     TIMESTAMP(9) WITH LOCAL TIME ZONE,
        updated     TIMESTAMP(9) WITH LOCAL TIME ZONE,
        CONSTRAINT aio_embed_jobs_pk PRIMARY KEY (job_id)
    )
    """,
    # Lookups are predominantly per-client (list view), per-status
    # (reaper sweep), and per-target-db (database-update guard). All
    # three indexes guard against full-table scans as the row count
    # grows with workload.
    """
    CREATE INDEX IF NOT EXISTS aio_embed_jobs_client_ix
        ON aio_embed_jobs (client)
    """,
    """
    CREATE INDEX IF NOT EXISTS aio_embed_jobs_status_ix
        ON aio_embed_jobs (status)
    """,
    """
    CREATE INDEX IF NOT EXISTS aio_embed_jobs_target_db_ix
        ON aio_embed_jobs (target_db)
    """,
    """
    CREATE TABLE IF NOT EXISTS aio_auth_authority (
        authority_id             NUMBER(1) DEFAULT 1 NOT NULL,
        auth_mode                VARCHAR2(32) NOT NULL,
        schema_version           NUMBER(9) NOT NULL,
        database_identity        VARCHAR2(255) NOT NULL,
        application_schema       VARCHAR2(128) NOT NULL,
        oidc_issuer              VARCHAR2(2048),
        oidc_admin_subject       VARCHAR2(1024),
        initialized              TIMESTAMP(9) WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
        last_validated           TIMESTAMP(9) WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
        CONSTRAINT aio_auth_authority_pk PRIMARY KEY (authority_id),
        CONSTRAINT aio_auth_authority_singleton_ck CHECK (authority_id = 1),
        CONSTRAINT aio_auth_authority_mode_ck
            CHECK (auth_mode IN ('LOCAL_USERS', 'OIDC')),
        CONSTRAINT aio_auth_authority_oidc_ck CHECK (
            (auth_mode = 'OIDC' AND oidc_issuer IS NOT NULL AND oidc_admin_subject IS NOT NULL)
            OR (auth_mode <> 'OIDC' AND oidc_issuer IS NULL AND oidc_admin_subject IS NULL)
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS aio_users (
        user_id             RAW(16) NOT NULL,
        username            VARCHAR2(255) NOT NULL,
        auth_source         VARCHAR2(32) NOT NULL,
        database_username   VARCHAR2(128),
        issuer              VARCHAR2(2048),
        subject             VARCHAR2(1024),
        display_name        VARCHAR2(255),
        email               VARCHAR2(320),
        role                VARCHAR2(16) NOT NULL,
        status              VARCHAR2(16) DEFAULT 'ACTIVE' NOT NULL,
        created             TIMESTAMP(9) WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
        updated             TIMESTAMP(9) WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
        last_login          TIMESTAMP(9) WITH TIME ZONE,
        CONSTRAINT aio_users_pk PRIMARY KEY (user_id),
        CONSTRAINT aio_users_database_uq UNIQUE (database_username),
        CONSTRAINT aio_users_oidc_uq UNIQUE (issuer, subject),
        CONSTRAINT aio_users_source_ck CHECK (auth_source IN ('DATABASE_END_USER', 'OIDC')),
        CONSTRAINT aio_users_role_ck CHECK (role IN ('ADMIN', 'MEMBER')),
        CONSTRAINT aio_users_status_ck CHECK (status IN ('ACTIVE', 'DISABLED')),
        CONSTRAINT aio_users_identity_ck CHECK (
            (auth_source = 'DATABASE_END_USER' AND database_username IS NOT NULL
                AND issuer IS NULL AND subject IS NULL)
            OR (auth_source = 'OIDC' AND issuer IS NOT NULL AND subject IS NOT NULL)
        ),
        CONSTRAINT aio_users_admin_ck CHECK (
            role <> 'ADMIN'
            OR user_id = 'F4304C284BF65E7DA28433CC0A5A6C01'
        )
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS aio_auth_sessions (
        session_id      RAW(16) NOT NULL,
        user_id         RAW(16) NOT NULL,
        token_digest    RAW(32) NOT NULL,
        created         TIMESTAMP(9) WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
        expires         TIMESTAMP(9) WITH TIME ZONE NOT NULL,
        last_seen       TIMESTAMP(9) WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
        revoked         TIMESTAMP(9) WITH TIME ZONE,
        remote_address  VARCHAR2(255),
        CONSTRAINT aio_auth_sessions_pk PRIMARY KEY (session_id),
        CONSTRAINT aio_auth_sessions_token_uq UNIQUE (token_digest),
        CONSTRAINT aio_auth_sessions_user_fk FOREIGN KEY (user_id)
            REFERENCES aio_users(user_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS aio_auth_sessions_user_ix
        ON aio_auth_sessions (user_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS aio_auth_sessions_expiry_ix
        ON aio_auth_sessions (expires, revoked)
    """,
    """
    CREATE TABLE IF NOT EXISTS aio_auth_audit (
        event_id       RAW(16) NOT NULL,
        event_type     VARCHAR2(64) NOT NULL,
        user_id        RAW(16) NOT NULL,
        old_identity   VARCHAR2(2048),
        new_identity   VARCHAR2(2048),
        created        TIMESTAMP(9) WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
        CONSTRAINT aio_auth_audit_pk PRIMARY KEY (event_id),
        CONSTRAINT aio_auth_audit_user_fk FOREIGN KEY (user_id) REFERENCES aio_users(user_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS aio_auth_audit_user_ix
        ON aio_auth_audit (user_id, created)
    """,
]

REQUIRED_SCHEMA_TABLES = frozenset(
    {
        "AIO_SETTINGS",
        "AIO_TESTSETS",
        "AIO_TESTSET_QA",
        "AIO_EVALUATIONS",
        "AIO_EMBED_JOBS",
        "AIO_AUTH_AUTHORITY",
        "AIO_USERS",
        "AIO_AUTH_SESSIONS",
        "AIO_AUTH_AUDIT",
    }
)

REQUIRED_SCHEMA_INDEXES = frozenset(
    {
        "AIO_EMBED_JOBS_CLIENT_IX",
        "AIO_EMBED_JOBS_STATUS_IX",
        "AIO_EMBED_JOBS_TARGET_DB_IX",
        "AIO_AUTH_SESSIONS_USER_IX",
        "AIO_AUTH_SESSIONS_EXPIRY_IX",
        "AIO_AUTH_AUDIT_USER_IX",
    }
)
