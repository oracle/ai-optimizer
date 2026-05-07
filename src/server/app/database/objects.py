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
]
