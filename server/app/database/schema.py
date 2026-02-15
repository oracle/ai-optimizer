"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Raw DDL statements for Oracle AI Database schema bootstrap.
"""
# spell-checker: ignore testsets testset

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
        rag_report          BLOB,
        CONSTRAINT aio_evaluations_pk PRIMARY KEY (eid),
        CONSTRAINT aio_evaluations_fk FOREIGN KEY (tid)
            REFERENCES aio_testsets(tid) ON DELETE CASCADE,
        CONSTRAINT aio_evaluations_uq UNIQUE (eid, evaluated)
    )
    """,
]
