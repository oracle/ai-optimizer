"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Raw DDL statements for Oracle AI Database schema bootstrap.
"""
# spell-checker: ignore testsets testset

SCHEMA_DDL = [
    """
    CREATE TABLE IF NOT EXISTS oai_testsets (
        tid     RAW(16) DEFAULT SYS_GUID(),
        name    VARCHAR2(255) NOT NULL,
        created TIMESTAMP(9) WITH LOCAL TIME ZONE,
        CONSTRAINT oai_testsets_pk PRIMARY KEY (tid),
        CONSTRAINT oai_testsets_uq UNIQUE (name, created)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS oai_testset_qa (
        tid      RAW(16) DEFAULT SYS_GUID(),
        qa_data  JSON,
        CONSTRAINT oai_testset_qa_fk FOREIGN KEY (tid)
            REFERENCES oai_testsets(tid) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS oai_evaluations (
        eid                 RAW(16) DEFAULT SYS_GUID(),
        tid                 RAW(16) DEFAULT SYS_GUID(),
        evaluated           TIMESTAMP(9) WITH LOCAL TIME ZONE,
        correctness         NUMBER DEFAULT 0,
        settings            JSON,
        rag_report          BLOB,
        CONSTRAINT oai_evaluations_pk PRIMARY KEY (eid),
        CONSTRAINT oai_evaluations_fk FOREIGN KEY (tid)
            REFERENCES oai_testsets(tid) ON DELETE CASCADE,
        CONSTRAINT oai_evaluations_uq UNIQUE (eid, evaluated)
    )
    """,
]
