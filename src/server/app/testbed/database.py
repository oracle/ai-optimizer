"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Async database operations for testbed tables (aio_testsets, aio_testset_qa, aio_evaluations).
"""
# spell-checker:ignore testsets testset giskard setinputsizes

import json
import logging
from typing import Optional

import oracledb
from pydantic import ValidationError

from server.app.database.sql import execute_sql
from server.app.testbed.schemas import RAGReportPayload

LOGGER = logging.getLogger(__name__)

_ISO_TS_FMT = """'YYYY-MM-DD"T"HH24:MI:SS.FF'"""


def _hex_to_raw(hex_str: str | None) -> bytes | None:
    """Convert a hex ID string to bytes for RAW column binding."""
    return bytes.fromhex(hex_str) if hex_str else None


async def get_testsets(conn: oracledb.AsyncConnection) -> list[dict]:
    """Get all testsets ordered by creation date."""
    sql = f"SELECT tid, name, to_char(created, {_ISO_TS_FMT}) FROM aio_testsets ORDER BY created"
    results = await execute_sql(conn, sql)
    if not results:
        return []
    return [{"tid": tid.hex(), "name": name, "created": created} for tid, name, created in results]


async def get_testset_qa(conn: oracledb.AsyncConnection, tid: str) -> dict:
    """Get Q&A data for a testset by ID."""
    LOGGER.info("Getting TestSet Q&A for TID: %s", tid)
    sql = "SELECT qa_data FROM aio_testset_qa WHERE tid=:tid"
    results = await execute_sql(conn, sql, {"tid": _hex_to_raw(tid)})
    qa_data = [row[0] for row in results] if results else []
    return {"qa_data": qa_data}


async def get_evaluations(conn: oracledb.AsyncConnection, tid: str) -> list[dict]:
    """Get evaluations for a testset, newest first."""
    sql = f"""
        SELECT eid, to_char(evaluated, {_ISO_TS_FMT}), correctness
          FROM aio_evaluations WHERE tid=:tid ORDER BY evaluated DESC
        """
    results = await execute_sql(conn, sql, {"tid": _hex_to_raw(tid)})
    if not results:
        return []
    return [
        {"eid": eid.hex(), "evaluated": evaluated, "correctness": correctness}
        for eid, evaluated, correctness in results
    ]


async def delete_testset(conn: oracledb.AsyncConnection, tid: str) -> None:
    """Delete a testset (cascades to Q&A records via FK)."""
    sql = "DELETE FROM aio_testsets WHERE tid = :tid"
    await execute_sql(conn, sql, {"tid": _hex_to_raw(tid)})
    await conn.commit()


async def upsert_qa(
    conn: oracledb.AsyncConnection,
    name: str,
    created: str,
    json_data: str,
    tid: Optional[str] = None,
) -> str:
    """Upsert testset and Q&A records, returning the testset ID (hex)."""
    LOGGER.info("Upsert TestSet: %s - %s", name, created)
    parsed_data = json.loads(json_data)
    if not isinstance(parsed_data, list):
        parsed_data = [parsed_data]
    json_data = json.dumps(parsed_data)

    plsql = """
        DECLARE
            l_tid      aio_testsets.tid%TYPE := :tid;
            l_name     aio_testsets.name%TYPE := :name;
            l_created  aio_testsets.created%TYPE := TO_TIMESTAMP(:created ,'YYYY-MM-DD"T"HH24:MI:SS.FF');
            l_qa_array JSON_ARRAY_T := JSON_ARRAY_T(:json_array);
            l_qa_obj   JSON_OBJECT_T;
            l_qa_str   VARCHAR2(32000);
        BEGIN
            BEGIN
                IF l_tid IS NULL THEN
                    SELECT tid INTO l_tid
                    FROM aio_testsets
                    WHERE created = l_created
                    AND name = l_name;
                ELSE
                    UPDATE aio_testsets SET name = l_name WHERE tid = l_tid;
                END IF;
                DELETE FROM aio_testset_qa WHERE tid = l_tid;
            EXCEPTION WHEN NO_DATA_FOUND THEN
                INSERT INTO aio_testsets (name, created) VALUES (l_name, l_created)
                RETURNING tid INTO l_tid;
            END;
            FOR i IN 0 .. l_qa_array.get_size - 1
            LOOP
                l_qa_obj := TREAT(l_qa_array.get(i) AS json_object_t);
                l_qa_str := l_qa_obj.stringify();
                INSERT INTO aio_testset_qa (tid, qa_data) VALUES (l_tid, l_qa_str);
            END LOOP;
            :out_tid := l_tid;
        END;
    """
    async with conn.cursor() as cursor:
        out_tid = cursor.var(oracledb.DB_TYPE_RAW)
        await cursor.execute(
            plsql,
            {"tid": _hex_to_raw(tid), "name": name, "created": created, "json_array": json_data, "out_tid": out_tid},
        )
    return out_tid.getvalue().hex()


async def insert_evaluation(
    conn: oracledb.AsyncConnection,
    tid: str,
    evaluated: str,
    correctness: float,
    settings_json: str,
    rag_report: dict,
) -> str:
    """Insert an evaluation record, returning the evaluation ID (hex)."""
    LOGGER.info("Insert evaluation; TID: %s", tid)
    plsql = """
        DECLARE
            l_eid       aio_evaluations.eid%TYPE;
            l_evaluated aio_evaluations.evaluated%TYPE := TO_TIMESTAMP(:evaluated ,'YYYY-MM-DD"T"HH24:MI:SS.FF');
        BEGIN
            INSERT INTO aio_evaluations (
                tid, evaluated, correctness, settings, rag_report)
            VALUES (
                :tid, l_evaluated, :correctness, :settings, :rag_report)
            RETURNING eid INTO l_eid;
            :out_eid := l_eid;
        END;
    """
    async with conn.cursor() as cursor:
        out_eid = cursor.var(oracledb.DB_TYPE_RAW)
        cursor.setinputsizes(
            settings=oracledb.DB_TYPE_JSON,
            rag_report=oracledb.DB_TYPE_JSON,
        )
        await cursor.execute(
            plsql,
            {
                "tid": _hex_to_raw(tid),
                "evaluated": evaluated,
                "correctness": correctness,
                "settings": settings_json,
                "rag_report": rag_report,
                "out_eid": out_eid,
            },
        )
    return out_eid.getvalue().hex()


async def process_report(conn: oracledb.AsyncConnection, eid: str) -> Optional[dict]:
    """Load an evaluation's stored JSON report and surface its metrics."""
    sql = f"""
        SELECT eid, to_char(evaluated, {_ISO_TS_FMT}) as evaluated, correctness, settings, rag_report
          FROM aio_evaluations WHERE eid=:eid
         ORDER BY evaluated
    """
    results = await execute_sql(conn, sql, {"eid": _hex_to_raw(eid)})
    if not results:
        return None

    eid_val, evaluated, correctness, settings_val, rag_report_val = results[0]
    try:
        payload = RAGReportPayload.model_validate(rag_report_val)
    except ValidationError:
        return None

    return {
        "eid": eid_val.hex() if hasattr(eid_val, "hex") else eid_val,
        "evaluated": evaluated,
        "correctness": correctness,
        "settings": settings_val if isinstance(settings_val, dict) else json.loads(settings_val),
        "report": payload.report,
        "correct_by_topic": payload.correct_by_topic,
        "failures": payload.failures,
        "html_report": "<html><body></body></html>",
    }
