"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for testbed async database operations.
"""
# spell-checker:disable

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.app.testbed.database import (
    _hex_to_raw,
    delete_testset,
    get_evaluations,
    get_testset_qa,
    get_testsets,
    insert_evaluation,
    process_report,
    upsert_qa,
)


def _make_async_cursor(out_value=None):
    """Build a mock cursor that works as an async context manager with OUT bind support."""
    cursor = AsyncMock()
    # var() and setinputsizes() are synchronous on oracledb cursors
    out_var = MagicMock()
    out_var.getvalue.return_value = out_value
    cursor.var = MagicMock(return_value=out_var)
    cursor.setinputsizes = MagicMock()

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=cursor)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, cursor, out_var


# ---------------------------------------------------------------------------
# _hex_to_raw
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_hex_to_raw_converts():
    """Converts hex string to bytes."""
    assert _hex_to_raw("aabbccdd") == bytes.fromhex("aabbccdd")


@pytest.mark.unit
def test_hex_to_raw_none():
    """Returns None for None input."""
    assert _hex_to_raw(None) is None


@pytest.mark.unit
def test_hex_to_raw_empty():
    """Returns None for empty string."""
    assert _hex_to_raw("") is None


# ---------------------------------------------------------------------------
# get_testsets
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_testsets_empty():
    """Returns empty list when no testsets exist."""
    conn = AsyncMock()
    with patch("server.app.testbed.database.execute_sql", new_callable=AsyncMock, return_value=None):
        result = await get_testsets(conn)
    assert result == []


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_testsets_with_data():
    """Returns formatted testset list from DB rows."""
    tid_bytes = bytes.fromhex("aabbccdd")
    rows = [(tid_bytes, "Test Set", "2026-01-01T00:00:00")]
    conn = AsyncMock()
    with patch("server.app.testbed.database.execute_sql", new_callable=AsyncMock, return_value=rows):
        result = await get_testsets(conn)
    assert len(result) == 1
    assert result[0]["tid"] == "aabbccdd"
    assert result[0]["name"] == "Test Set"


# ---------------------------------------------------------------------------
# get_testset_qa
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_testset_qa_empty():
    """Returns empty qa_data when no records found."""
    conn = AsyncMock()
    with patch("server.app.testbed.database.execute_sql", new_callable=AsyncMock, return_value=None):
        result = await get_testset_qa(conn, "AABB")
    assert result == {"qa_data": []}


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_testset_qa_with_data():
    """Returns Q&A data extracted from tuples."""
    qa_obj = {"question": "What?", "answer": "Yes."}
    rows = [(qa_obj,)]
    conn = AsyncMock()
    mock_exec = AsyncMock(return_value=rows)
    with patch("server.app.testbed.database.execute_sql", mock_exec):
        result = await get_testset_qa(conn, "AABB")
    assert result["qa_data"] == [qa_obj]
    # Verify hex ID was converted to bytes for RAW column binding
    binds = mock_exec.call_args[0][2]
    assert binds["tid"] == bytes.fromhex("AABB")


# ---------------------------------------------------------------------------
# get_evaluations
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_evaluations_empty():
    """Returns empty list when no evaluations exist."""
    conn = AsyncMock()
    with patch("server.app.testbed.database.execute_sql", new_callable=AsyncMock, return_value=None):
        result = await get_evaluations(conn, "AABB")
    assert result == []


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_evaluations_with_data():
    """Returns formatted evaluation list."""
    eid_bytes = bytes.fromhex("11223344")
    rows = [(eid_bytes, "2026-01-01T00:00:00", 0.85)]
    conn = AsyncMock()
    with patch("server.app.testbed.database.execute_sql", new_callable=AsyncMock, return_value=rows):
        result = await get_evaluations(conn, "AABB")
    assert len(result) == 1
    assert result[0]["eid"] == "11223344"
    assert result[0]["correctness"] == 0.85


# ---------------------------------------------------------------------------
# delete_testset
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_testset():
    """Deletes testset and commits."""
    conn = AsyncMock()
    with patch("server.app.testbed.database.execute_sql", new_callable=AsyncMock):
        await delete_testset(conn, "AABB")
    conn.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# upsert_qa
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_upsert_qa():
    """Executes PL/SQL and returns hex TID from OUT bind."""
    tid_bytes = bytes.fromhex("deadbeef")
    ctx, cursor, _ = _make_async_cursor(out_value=tid_bytes)

    conn = MagicMock()
    conn.cursor.return_value = ctx

    result = await upsert_qa(conn, "Test", "2026-01-01T00:00:00", json.dumps({"q": "a"}))
    assert result == "deadbeef"
    cursor.execute.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.anyio
async def test_upsert_qa_wraps_single_object():
    """Single QA object is wrapped in array before PL/SQL execution."""
    tid_bytes = bytes.fromhex("deadbeef")
    ctx, cursor, _ = _make_async_cursor(out_value=tid_bytes)

    conn = MagicMock()
    conn.cursor.return_value = ctx

    await upsert_qa(conn, "Test", "2026-01-01T00:00:00", json.dumps({"q": "a"}))
    call_args = cursor.execute.call_args
    binds = call_args[0][1]
    parsed = json.loads(binds["json_array"])
    assert isinstance(parsed, list)


# ---------------------------------------------------------------------------
# insert_evaluation
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_insert_evaluation():
    """Executes PL/SQL and returns hex EID from OUT bind."""
    eid_bytes = bytes.fromhex("cafebabe")
    ctx, cursor, _ = _make_async_cursor(out_value=eid_bytes)

    conn = MagicMock()
    conn.cursor.return_value = ctx

    result = await insert_evaluation(
        conn,
        tid="AABB",
        evaluated="2026-01-01T00:00:00",
        correctness=0.9,
        settings_json='{"client": "test"}',
        rag_report=b"pickled_data",
    )
    assert result == "cafebabe"
    cursor.setinputsizes.assert_called_once()


# ---------------------------------------------------------------------------
# process_report
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_process_report_not_found():
    """Returns None when evaluation not found."""
    conn = AsyncMock()
    with patch("server.app.testbed.database.execute_sql", new_callable=AsyncMock, return_value=None):
        result = await process_report(conn, "AABB")
    assert result is None


@pytest.mark.unit
@pytest.mark.anyio
async def test_process_report_with_data():
    """Unpickles report and extracts metrics."""
    mock_report = MagicMock()
    mock_df = MagicMock()
    mock_df.to_dict.return_value = {"col": "data"}
    mock_report.to_pandas.return_value = mock_df

    mock_topic = MagicMock()
    mock_topic.to_dict.return_value = {"topic": "scores"}
    mock_report.correctness_by_topic.return_value = mock_topic

    mock_failures = MagicMock()
    mock_failures.to_dict.return_value = {"fail": "info"}
    mock_report.failures = mock_failures

    eid_bytes = bytes.fromhex("aabbccdd")
    settings_dict = {"client": "test"}

    rows = [(eid_bytes, "2026-01-01T00:00:00", 0.85, settings_dict, b"placeholder")]
    conn = AsyncMock()
    with (
        patch("server.app.testbed.database.execute_sql", new_callable=AsyncMock, return_value=rows),
        patch("server.app.testbed.database.pickle.loads", return_value=mock_report),
    ):
        result = await process_report(conn, "AABBCCDD")

    assert result is not None
    assert result["eid"] == "aabbccdd"
    assert result["correctness"] == 0.85
    assert result["report"] == {"col": "data"}
    assert result["correct_by_topic"] == {"topic": "scores"}
    assert result["failures"] == {"fail": "info"}
    assert result["settings"] == settings_dict
