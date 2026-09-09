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
            BEGIN
                EXECUTE IMMEDIATE 'ALTER TABLE ' || rec.table_name ||
                    ' RENAME TO ' || 'AIO_' || SUBSTR(rec.table_name, 5);
            EXCEPTION WHEN OTHERS THEN NULL;
            END;
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
        l_count PLS_INTEGER;
    BEGIN
        SELECT COUNT(*) INTO l_count FROM user_tab_columns
         WHERE table_name = 'AIO_PRINCIPAL_SESSIONS' AND column_name = 'PRINCIPAL_ID';
        IF l_count = 0 THEN
            EXECUTE IMMEDIATE 'ALTER TABLE aio_principal_sessions ADD (principal_id VARCHAR2(36))';
        END IF;
        SELECT COUNT(*) INTO l_count FROM user_tab_columns
         WHERE table_name = 'AIO_TESTSETS' AND column_name = 'OWNER_PRINCIPAL_ID';
        IF l_count = 0 THEN
            EXECUTE IMMEDIATE 'ALTER TABLE aio_testsets ADD (owner_principal_id VARCHAR2(36))';
        END IF;
        SELECT COUNT(*) INTO l_count FROM user_tab_columns
         WHERE table_name = 'AIO_AUTH_TRANSACTIONS' AND column_name = 'DOWNSTREAM_STATE';
        IF l_count = 0 THEN
            EXECUTE IMMEDIATE 'ALTER TABLE aio_auth_transactions ADD (downstream_state VARCHAR2(2048))';
        END IF;
    EXCEPTION WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
    END;
    """,
]

SCHEMA_DDL = [
    """
    CREATE TABLE IF NOT EXISTS aio_principals (
        principal_id VARCHAR2(36) NOT NULL,
        display_name VARCHAR2(320) NOT NULL,
        email VARCHAR2(320),
        active BOOLEAN NOT NULL,
        created TIMESTAMP(9) WITH LOCAL TIME ZONE,
        updated TIMESTAMP(9) WITH LOCAL TIME ZONE,
        CONSTRAINT aio_principals_pk PRIMARY KEY (principal_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS aio_principal_identities (
        principal_id VARCHAR2(36) NOT NULL,
        issuer VARCHAR2(2048) NOT NULL,
        subject VARCHAR2(2048) NOT NULL,
        last_login TIMESTAMP(9) WITH LOCAL TIME ZONE,
        created TIMESTAMP(9) WITH LOCAL TIME ZONE,
        CONSTRAINT aio_principal_identities_pk PRIMARY KEY (issuer, subject),
        CONSTRAINT aio_principal_identities_principal_fk FOREIGN KEY (principal_id)
            REFERENCES aio_principals(principal_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS aio_principal_identities_principal_ix
        ON aio_principal_identities (principal_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS aio_principal_roles (
        principal_id VARCHAR2(36) NOT NULL,
        role VARCHAR2(255) NOT NULL,
        source VARCHAR2(255) NOT NULL,
        created TIMESTAMP(9) WITH LOCAL TIME ZONE,
        CONSTRAINT aio_principal_roles_pk PRIMARY KEY (principal_id, role, source),
        CONSTRAINT aio_principal_roles_principal_fk FOREIGN KEY (principal_id)
            REFERENCES aio_principals(principal_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS aio_local_accounts (
        principal_id VARCHAR2(36) NOT NULL,
        username VARCHAR2(320) NOT NULL,
        password_hash CLOB NOT NULL,
        created TIMESTAMP(9) WITH LOCAL TIME ZONE,
        updated TIMESTAMP(9) WITH LOCAL TIME ZONE,
        CONSTRAINT aio_local_accounts_pk PRIMARY KEY (principal_id),
        CONSTRAINT aio_local_accounts_username_uq UNIQUE (username),
        CONSTRAINT aio_local_accounts_principal_fk FOREIGN KEY (principal_id)
            REFERENCES aio_principals(principal_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS aio_auth_clients (
        client_id VARCHAR2(2048) NOT NULL,
        redirect_uris JSON NOT NULL,
        allowed_scopes JSON NOT NULL,
        is_public BOOLEAN NOT NULL,
        created TIMESTAMP(9) WITH LOCAL TIME ZONE,
        updated TIMESTAMP(9) WITH LOCAL TIME ZONE,
        CONSTRAINT aio_auth_clients_pk PRIMARY KEY (client_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS aio_auth_transactions (
        state VARCHAR2(128) NOT NULL,
        downstream_state VARCHAR2(2048) NOT NULL,
        client_id VARCHAR2(2048) NOT NULL,
        redirect_uri VARCHAR2(2048) NOT NULL,
        scope VARCHAR2(4000) NOT NULL,
        nonce VARCHAR2(2048) NOT NULL,
        code_challenge VARCHAR2(256) NOT NULL,
        upstream_nonce VARCHAR2(256) NOT NULL,
        upstream_verifier VARCHAR2(256) NOT NULL,
        expires_at TIMESTAMP(9) WITH LOCAL TIME ZONE NOT NULL,
        used BOOLEAN NOT NULL,
        created TIMESTAMP(9) WITH LOCAL TIME ZONE,
        CONSTRAINT aio_auth_transactions_pk PRIMARY KEY (state)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS aio_auth_codes (
        code_digest VARCHAR2(64) NOT NULL,
        client_id VARCHAR2(2048) NOT NULL,
        principal_id VARCHAR2(36) NOT NULL,
        redirect_uri VARCHAR2(2048) NOT NULL,
        scope VARCHAR2(4000) NOT NULL,
        nonce VARCHAR2(2048) NOT NULL,
        code_challenge VARCHAR2(256) NOT NULL,
        expires_at TIMESTAMP(9) WITH LOCAL TIME ZONE NOT NULL,
        used BOOLEAN NOT NULL,
        created TIMESTAMP(9) WITH LOCAL TIME ZONE,
        CONSTRAINT aio_auth_codes_pk PRIMARY KEY (code_digest),
        CONSTRAINT aio_auth_codes_principal_fk FOREIGN KEY (principal_id)
            REFERENCES aio_principals(principal_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS aio_auth_codes_expiry_ix ON aio_auth_codes (expires_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS aio_auth_login_sessions (
        session_digest VARCHAR2(64) NOT NULL,
        principal_id VARCHAR2(36) NOT NULL,
        expires_at TIMESTAMP(9) WITH LOCAL TIME ZONE NOT NULL,
        revoked BOOLEAN NOT NULL,
        created TIMESTAMP(9) WITH LOCAL TIME ZONE,
        CONSTRAINT aio_auth_login_sessions_pk PRIMARY KEY (session_digest),
        CONSTRAINT aio_auth_login_sessions_principal_fk FOREIGN KEY (principal_id)
            REFERENCES aio_principals(principal_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS aio_auth_access_tokens (
        token_digest VARCHAR2(64) NOT NULL,
        principal_id VARCHAR2(36) NOT NULL,
        client_id VARCHAR2(2048) NOT NULL,
        scope VARCHAR2(4000) NOT NULL,
        expires_at TIMESTAMP(9) WITH LOCAL TIME ZONE NOT NULL,
        revoked BOOLEAN NOT NULL,
        created TIMESTAMP(9) WITH LOCAL TIME ZONE,
        CONSTRAINT aio_auth_access_tokens_pk PRIMARY KEY (token_digest),
        CONSTRAINT aio_auth_access_tokens_principal_fk FOREIGN KEY (principal_id)
            REFERENCES aio_principals(principal_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS aio_auth_access_tokens_principal_ix ON aio_auth_access_tokens (principal_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS aio_auth_signing_keys (
        key_id VARCHAR2(128) NOT NULL,
        private_key_pem CLOB NOT NULL,
        active BOOLEAN NOT NULL,
        created TIMESTAMP(9) WITH LOCAL TIME ZONE,
        CONSTRAINT aio_auth_signing_keys_pk PRIMARY KEY (key_id)
    )
    """,
    # Principal-authenticated session ownership is independent from legacy
    # ``aio_settings.client`` rows so an existing caller-supplied ID is never
    # silently assigned to a newly authenticated principal.
    """
    CREATE TABLE IF NOT EXISTS aio_principal_sessions (
        session_id  VARCHAR2(255) NOT NULL,
        principal_id VARCHAR2(36) NOT NULL,
        created     TIMESTAMP(9) WITH LOCAL TIME ZONE,
        updated     TIMESTAMP(9) WITH LOCAL TIME ZONE,
        CONSTRAINT aio_principal_sessions_pk PRIMARY KEY (session_id),
        CONSTRAINT aio_principal_sessions_principal_fk FOREIGN KEY (principal_id)
            REFERENCES aio_principals(principal_id) ON DELETE CASCADE
    )
    """,
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
        tid          RAW(16) DEFAULT SYS_GUID(),
        name         VARCHAR2(255) NOT NULL,
        created      TIMESTAMP(9) WITH LOCAL TIME ZONE,
        owner_principal_id VARCHAR2(36),
        CONSTRAINT aio_testsets_pk PRIMARY KEY (tid),
        CONSTRAINT aio_testsets_uq UNIQUE (name, created)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS aio_testsets_owner_ix
        ON aio_testsets (owner_principal_id)
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
]
