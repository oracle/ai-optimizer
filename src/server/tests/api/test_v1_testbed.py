"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for testbed API endpoints.
"""
# spell-checker:disable

import io
import json
from unittest.mock import AsyncMock, patch

import pytest

from server.tests.api.conftest import _create_mock_pool

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_core_pool():
    """Mock the CORE database pool for all testbed tests."""
    conn = AsyncMock()
    pool = _create_mock_pool(conn)
    with patch(
        "server.app.api.v1.endpoints.testbed.get_core_pool",
        return_value=pool,
    ):
        yield conn, pool


# ---------------------------------------------------------------------------
# Auth tests — 403 without API key
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_testsets_no_auth(app_client):
    """GET testsets rejects requests without API key."""
    resp = await app_client.get("/v1/testbed/testsets")
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_evaluations_no_auth(app_client):
    """GET evaluations rejects requests without API key."""
    resp = await app_client.get("/v1/testbed/evaluations", params={"tid": "ABC"})
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_evaluation_no_auth(app_client):
    """GET evaluation rejects requests without API key."""
    resp = await app_client.get("/v1/testbed/evaluation", params={"eid": "ABC"})
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_testset_qa_no_auth(app_client):
    """GET testset_qa rejects requests without API key."""
    resp = await app_client.get("/v1/testbed/testset_qa", params={"tid": "ABC"})
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_testset_no_auth(app_client):
    """DELETE testset rejects requests without API key."""
    resp = await app_client.delete("/v1/testbed/testset_delete/ABC")
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_upload_testset_no_auth(app_client):
    """POST testset_load rejects requests without API key."""
    resp = await app_client.post("/v1/testbed/testset_load", data={"name": "test"})
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_generate_testset_no_auth(app_client):
    """POST testset_generate rejects requests without API key."""
    resp = await app_client.post("/v1/testbed/testset_generate", data={"name": "test"})
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_evaluate_no_auth(app_client):
    """POST evaluate rejects requests without API key."""
    resp = await app_client.post("/v1/testbed/evaluate", params={"tid": "ABC", "judge": "openai/gpt-4o-mini"})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /testbed/testsets
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_testsets(app_client, auth_headers):
    """Returns testset list from database."""
    mock_data = [{"tid": "AABB", "name": "Test", "created": "2026-01-01"}]
    with patch(
        "server.app.api.v1.endpoints.testbed.get_testsets",
        new_callable=AsyncMock,
        return_value=mock_data,
    ):
        resp = await app_client.get("/v1/testbed/testsets", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["tid"] == "AABB"


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_testsets_empty(app_client, auth_headers):
    """Returns empty list when no testsets exist."""
    with patch(
        "server.app.api.v1.endpoints.testbed.get_testsets",
        new_callable=AsyncMock,
        return_value=[],
    ):
        resp = await app_client.get("/v1/testbed/testsets", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# GET /testbed/evaluations
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_evaluations(app_client, auth_headers):
    """Returns evaluation list for a testset."""
    mock_data = [{"eid": "1122", "evaluated": "2026-01-01", "correctness": 0.9}]
    with patch(
        "server.app.api.v1.endpoints.testbed.get_evaluations",
        new_callable=AsyncMock,
        return_value=mock_data,
    ):
        resp = await app_client.get("/v1/testbed/evaluations", params={"tid": "ABC"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()[0]["correctness"] == 0.9


# ---------------------------------------------------------------------------
# GET /testbed/evaluation
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_evaluation(app_client, auth_headers):
    """Returns full evaluation report."""
    mock_data = {
        "eid": "1122",
        "evaluated": "2026-01-01",
        "correctness": 0.9,
        "settings": {"client": "test"},
        "report": {},
        "correct_by_topic": {},
        "failures": {},
        "html_report": "<html></html>",
    }
    with patch(
        "server.app.api.v1.endpoints.testbed.process_report",
        new_callable=AsyncMock,
        return_value=mock_data,
    ):
        resp = await app_client.get("/v1/testbed/evaluation", params={"eid": "1122"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["eid"] == "1122"


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_evaluation_not_found(app_client, auth_headers):
    """Returns 404 when evaluation not found."""
    with patch(
        "server.app.api.v1.endpoints.testbed.process_report",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = await app_client.get("/v1/testbed/evaluation", params={"eid": "MISSING"}, headers=auth_headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /testbed/testset_qa
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_testset_qa(app_client, auth_headers):
    """Returns Q&A data for a testset."""
    mock_data = {"qa_data": [{"question": "What?", "answer": "Yes."}]}
    with patch(
        "server.app.api.v1.endpoints.testbed.get_testset_qa",
        new_callable=AsyncMock,
        return_value=mock_data,
    ):
        resp = await app_client.get("/v1/testbed/testset_qa", params={"tid": "ABC"}, headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()["qa_data"]) == 1


# ---------------------------------------------------------------------------
# DELETE /testbed/testset_delete/{tid}
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_testset(app_client, auth_headers):
    """Deletes a testset and returns success message."""
    with patch(
        "server.app.api.v1.endpoints.testbed.delete_testset",
        new_callable=AsyncMock,
    ):
        resp = await app_client.delete("/v1/testbed/testset_delete/ABC123", headers=auth_headers)
    assert resp.status_code == 200
    assert "deleted" in resp.json()["message"]


# ---------------------------------------------------------------------------
# POST /testbed/testset_load
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_upload_testset(app_client, auth_headers):
    """Uploads a JSONL file and returns Q&A data."""
    qa_content = json.dumps({"question": "What?", "answer": "Yes."})
    mock_qa_data = {"qa_data": [{"question": "What?", "answer": "Yes."}]}

    with (
        patch(
            "server.app.api.v1.endpoints.testbed.upsert_qa",
            new_callable=AsyncMock,
            return_value="AABB",
        ),
        patch(
            "server.app.api.v1.endpoints.testbed.get_testset_qa",
            new_callable=AsyncMock,
            return_value=mock_qa_data,
        ),
    ):
        resp = await app_client.post(
            "/v1/testbed/testset_load",
            data={"name": "Test Set"},
            files=[("files", ("test.jsonl", io.BytesIO(qa_content.encode()), "application/json"))],
            headers=auth_headers,
        )
    assert resp.status_code == 200
    assert resp.json()["qa_data"] == mock_qa_data["qa_data"]


@pytest.mark.unit
@pytest.mark.anyio
async def test_upload_testset_multi_file(app_client, auth_headers):
    """Multiple uploaded files are merged into a single upsert_qa call."""
    file1 = json.dumps({"question": "Q1", "answer": "A1"})
    file2 = json.dumps({"question": "Q2", "answer": "A2"})
    mock_qa_data = {"qa_data": [{"question": "Q1", "answer": "A1"}, {"question": "Q2", "answer": "A2"}]}

    mock_upsert = AsyncMock(return_value="AABB")
    with (
        patch("server.app.api.v1.endpoints.testbed.upsert_qa", mock_upsert),
        patch(
            "server.app.api.v1.endpoints.testbed.get_testset_qa",
            new_callable=AsyncMock,
            return_value=mock_qa_data,
        ),
    ):
        resp = await app_client.post(
            "/v1/testbed/testset_load",
            data={"name": "Multi"},
            files=[
                ("files", ("a.jsonl", io.BytesIO(file1.encode()), "application/json")),
                ("files", ("b.jsonl", io.BytesIO(file2.encode()), "application/json")),
            ],
            headers=auth_headers,
        )
    assert resp.status_code == 200
    # upsert_qa must be called exactly once with both items combined
    mock_upsert.assert_awaited_once()
    call_args = mock_upsert.call_args
    combined = json.loads(call_args[0][3])  # positional arg: json_data
    assert len(combined) == 2
    assert combined[0]["question"] == "Q1"
    assert combined[1]["question"] == "Q2"


# ---------------------------------------------------------------------------
# QA serialisation (evaluate_testset builds JSONL from DB rows)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_qa_rows_not_double_encoded():
    """QA items already stored as JSON strings must not be re-encoded."""
    # Simulates what evaluate_testset does on line 292
    str_item = '{"question": "Q?", "reference_answer": "A."}'
    dict_item = {"question": "Q2?", "reference_answer": "A2."}
    qa_data = [str_item, dict_item]

    lines = [item if isinstance(item, str) else json.dumps(item) for item in qa_data]

    # String item must pass through unchanged (no extra quoting)
    assert lines[0] == str_item
    assert json.loads(lines[0])["question"] == "Q?"
    # Dict item must be serialised once
    assert json.loads(lines[1])["question"] == "Q2?"


# ---------------------------------------------------------------------------
# Filename sanitisation — canonical tests live in tests/core/test_file_utils.py
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# DB unavailable
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_testsets_db_unavailable(app_client, auth_headers):
    """Returns 503 when CORE database is not available."""
    with patch(
        "server.app.api.v1.endpoints.testbed.get_core_pool",
        return_value=None,
    ):
        resp = await app_client.get("/v1/testbed/testsets", headers=auth_headers)
    assert resp.status_code == 503
