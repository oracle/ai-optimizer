"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for testbed API endpoints.
"""
# spell-checker:disable

import io
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from server.tests.api.conftest import _create_mock_pool

VALID_TID = "0123456789abcdef0123456789abcdef"
VALID_EID = "fedcba9876543210fedcba9876543210"

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
    mock_data = [{"tid": VALID_TID, "name": "Test", "created": "2026-01-01"}]
    with patch(
        "server.app.api.v1.endpoints.testbed.get_testsets",
        new_callable=AsyncMock,
        return_value=mock_data,
    ):
        resp = await app_client.get("/v1/testbed/testsets", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["tid"] == VALID_TID


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
    mock_data = [{"eid": VALID_EID, "evaluated": "2026-01-01", "correctness": 0.9}]
    with patch(
        "server.app.api.v1.endpoints.testbed.get_evaluations",
        new_callable=AsyncMock,
        return_value=mock_data,
    ):
        resp = await app_client.get(
            "/v1/testbed/evaluations", params={"tid": VALID_TID}, headers=auth_headers
        )
    assert resp.status_code == 200
    assert resp.json()[0]["correctness"] == 0.9


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_evaluations_rejects_invalid_tid(app_client, auth_headers):
    """Invalid tid query values must fail validation before DB parsing."""
    with patch("server.app.api.v1.endpoints.testbed.get_evaluations", new_callable=AsyncMock) as mock_get:
        resp = await app_client.get("/v1/testbed/evaluations", params={"tid": "string"}, headers=auth_headers)

    assert resp.status_code == 422
    assert "tid" in resp.text
    mock_get.assert_not_awaited()


# ---------------------------------------------------------------------------
# GET /testbed/evaluation
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_evaluation(app_client, auth_headers):
    """Returns full evaluation report."""
    mock_data = {
        "eid": VALID_EID,
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
        resp = await app_client.get(
            "/v1/testbed/evaluation", params={"eid": VALID_EID}, headers=auth_headers
        )
    assert resp.status_code == 200
    assert resp.json()["eid"] == VALID_EID


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_evaluation_not_found(app_client, auth_headers):
    """Returns 404 when evaluation not found."""
    with patch(
        "server.app.api.v1.endpoints.testbed.process_report",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = await app_client.get(
            "/v1/testbed/evaluation", params={"eid": VALID_EID}, headers=auth_headers
        )
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_evaluation_rejects_invalid_eid(app_client, auth_headers):
    """Invalid eid query values must fail validation before DB parsing."""
    with patch("server.app.api.v1.endpoints.testbed.process_report", new_callable=AsyncMock) as mock_process:
        resp = await app_client.get("/v1/testbed/evaluation", params={"eid": "string"}, headers=auth_headers)

    assert resp.status_code == 422
    assert "eid" in resp.text
    mock_process.assert_not_awaited()


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
        resp = await app_client.get(
            "/v1/testbed/testset_qa", params={"tid": VALID_TID}, headers=auth_headers
        )
    assert resp.status_code == 200
    assert len(resp.json()["qa_data"]) == 1


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_testset_qa_rejects_invalid_tid(app_client, auth_headers):
    """Invalid tid query values must fail validation before DB parsing."""
    with patch("server.app.api.v1.endpoints.testbed.get_testset_qa", new_callable=AsyncMock) as mock_get:
        resp = await app_client.get("/v1/testbed/testset_qa", params={"tid": "string"}, headers=auth_headers)

    assert resp.status_code == 422
    assert "tid" in resp.text
    mock_get.assert_not_awaited()


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
        resp = await app_client.delete(
            f"/v1/testbed/testset_delete/{VALID_TID}", headers=auth_headers
        )
    assert resp.status_code == 200
    assert "deleted" in resp.json()["message"]


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_testset_rejects_invalid_tid(app_client, auth_headers):
    """Invalid tid path values must fail validation before DB parsing."""
    with patch("server.app.api.v1.endpoints.testbed.delete_testset", new_callable=AsyncMock) as mock_delete:
        resp = await app_client.delete("/v1/testbed/testset_delete/string", headers=auth_headers)

    assert resp.status_code == 422
    assert "tid" in resp.text
    mock_delete.assert_not_awaited()


# ---------------------------------------------------------------------------
# POST /testbed/testset_load
# ---------------------------------------------------------------------------


def _qa_record(**overrides):
    """Build a valid Giskard QA record for upload-path tests."""
    base = {
        "id": "00000000-0000-0000-0000-000000000001",
        "question": "What?",
        "reference_answer": "Yes.",
        "reference_context": "Context.",
        "conversation_history": [],
        "metadata": {},
    }
    base.update(overrides)
    return base


@pytest.mark.unit
@pytest.mark.anyio
async def test_upload_testset(app_client, auth_headers):
    """Uploads a JSONL file and returns Q&A data."""
    qa_content = json.dumps(_qa_record())
    mock_qa_data = {"qa_data": [_qa_record()]}

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
    rec1 = _qa_record(question="Q1", reference_answer="A1")
    rec2 = _qa_record(id="00000000-0000-0000-0000-000000000002", question="Q2", reference_answer="A2")
    file1 = json.dumps(rec1)
    file2 = json.dumps(rec2)
    mock_qa_data = {"qa_data": [rec1, rec2]}

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


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize(
    "bad_tid",
    [
        "string",          # Swagger's default placeholder
        "a" * 31,          # one char short
        "a" * 33,          # one char long
        "g" * 32,          # right length, non-hex
    ],
)
async def test_upload_testset_rejects_invalid_tid(app_client, auth_headers, bad_tid):
    """Non-32-hex tids must fail validation before any DB work."""
    qa_content = json.dumps({"question": "What?", "answer": "Yes."})

    with patch("server.app.api.v1.endpoints.testbed.upsert_qa", new_callable=AsyncMock) as mock_upsert:
        resp = await app_client.post(
            "/v1/testbed/testset_load",
            data={"name": "Test Set", "tid": bad_tid},
            files=[("files", ("test.jsonl", io.BytesIO(qa_content.encode()), "application/json"))],
            headers=auth_headers,
        )

    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["body", "tid"]
    mock_upsert.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.anyio
async def test_upload_testset_rejects_record_missing_required_fields(app_client, auth_headers):
    """A QA record without Giskard's required fields is rejected with 400 before DB upsert."""
    minimal = json.dumps({"question": "What?", "reference_answer": "Yes."})

    with patch("server.app.api.v1.endpoints.testbed.upsert_qa", new_callable=AsyncMock) as mock_upsert:
        resp = await app_client.post(
            "/v1/testbed/testset_load",
            data={"name": "Test Set"},
            files=[("files", ("incomplete.jsonl", io.BytesIO(minimal.encode()), "application/json"))],
            headers=auth_headers,
        )

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["message"] == "Invalid QA record at index 0 in 'incomplete.jsonl'."
    missing_fields = {tuple(err["loc"]) for err in detail["errors"]}
    assert ("id",) in missing_fields
    assert ("reference_context",) in missing_fields
    mock_upsert.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.anyio
async def test_upload_testset_rejects_malformed_json(app_client, auth_headers):
    """Unparseable upload content surfaces as 400, not an unhandled 500."""
    with patch("server.app.api.v1.endpoints.testbed.upsert_qa", new_callable=AsyncMock) as mock_upsert:
        resp = await app_client.post(
            "/v1/testbed/testset_load",
            data={"name": "Test Set"},
            files=[("files", ("bad.jsonl", io.BytesIO(b"{not json at all"), "application/json"))],
            headers=auth_headers,
        )

    assert resp.status_code == 400
    assert "bad.jsonl" in resp.text
    mock_upsert.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.anyio
async def test_upload_testset_rejects_wrong_field_type(app_client, auth_headers):
    """A QA record with a wrong-typed field is rejected with 400."""
    bad = _qa_record(conversation_history="not-a-list")

    with patch("server.app.api.v1.endpoints.testbed.upsert_qa", new_callable=AsyncMock) as mock_upsert:
        resp = await app_client.post(
            "/v1/testbed/testset_load",
            data={"name": "Test Set"},
            files=[("files", ("bad.jsonl", io.BytesIO(json.dumps(bad).encode()), "application/json"))],
            headers=auth_headers,
        )

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert ("conversation_history",) in {tuple(err["loc"]) for err in detail["errors"]}
    mock_upsert.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.anyio
async def test_upload_testset_rejects_unknown_fields(app_client, auth_headers):
    """Unknown extras are refused — Giskard's QATestset.load fails on extras at evaluate time."""
    rec = _qa_record(future_giskard_field=42)

    with patch("server.app.api.v1.endpoints.testbed.upsert_qa", new_callable=AsyncMock) as mock_upsert:
        resp = await app_client.post(
            "/v1/testbed/testset_load",
            data={"name": "Test Set"},
            files=[("files", ("with_extra.jsonl", io.BytesIO(json.dumps(rec).encode()), "application/json"))],
            headers=auth_headers,
        )

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert ("future_giskard_field",) in {tuple(err["loc"]) for err in detail["errors"]}
    mock_upsert.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.anyio
async def test_upload_testset_accepts_optional_questionsample_fields(app_client, auth_headers):
    """Giskard's optional QuestionSample fields (agent_answer, correctness) are accepted."""
    rec = _qa_record(agent_answer="model output", correctness=True)

    mock_upsert = AsyncMock(return_value="aabb")
    with (
        patch("server.app.api.v1.endpoints.testbed.upsert_qa", mock_upsert),
        patch(
            "server.app.api.v1.endpoints.testbed.get_testset_qa",
            new_callable=AsyncMock,
            return_value={"qa_data": [rec]},
        ),
    ):
        resp = await app_client.post(
            "/v1/testbed/testset_load",
            data={"name": "Test Set"},
            files=[("files", ("ok.jsonl", io.BytesIO(json.dumps(rec).encode()), "application/json"))],
            headers=auth_headers,
        )

    assert resp.status_code == 200
    stored = json.loads(mock_upsert.call_args[0][3])
    assert stored[0]["agent_answer"] == "model output"
    assert stored[0]["correctness"] is True


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize("bad_name", ["", "x" * 256])
async def test_upload_testset_rejects_invalid_name(app_client, auth_headers, bad_name):
    """Empty or oversized names must fail validation before DB upsert."""
    qa_content = json.dumps({"question": "What?", "answer": "Yes."})

    with patch("server.app.api.v1.endpoints.testbed.upsert_qa", new_callable=AsyncMock) as mock_upsert:
        resp = await app_client.post(
            "/v1/testbed/testset_load",
            data={"name": bad_name},
            files=[("files", ("test.jsonl", io.BytesIO(qa_content.encode()), "application/json"))],
            headers=auth_headers,
        )

    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["body", "name"]
    mock_upsert.assert_not_awaited()


# ---------------------------------------------------------------------------
# POST /testbed/evaluate
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_evaluate_rejects_invalid_tid(app_client, auth_headers):
    """Invalid tid query values must fail validation before DB loading."""
    with patch(
        "server.app.api.v1.endpoints.testbed._load_testset_from_db",
        new_callable=AsyncMock,
        side_effect=AssertionError("invalid tid reached DB loading"),
    ) as mock_load:
        resp = await app_client.post(
            "/v1/testbed/evaluate",
            params={"tid": "string", "judge": "openai/gpt-4o-mini"},
            headers=auth_headers,
        )

    assert resp.status_code == 422
    assert "tid" in resp.text
    mock_load.assert_not_awaited()


# ---------------------------------------------------------------------------
# _serialise_report — JSON-safety of the persisted Giskard report payload
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_serialise_report_coerces_nan_to_null():
    """NaN/Inf cells must coerce to None — strict JSON encoding rejects them."""
    from server.app.api.v1.endpoints.testbed import _serialise_report

    mixed_df = pd.DataFrame(
        {
            "question": ["Q1", "Q2"],
            "correct": [True, False],
            "correctness_reason": [float("nan"), "Wrong answer"],
        }
    )
    by_topic_df = pd.DataFrame({"score": [0.5, float("inf")]}, index=["topic_a", "topic_b"])
    failures_df = pd.DataFrame({"reason": [float("nan")]}, index=[0])

    report = MagicMock()
    report.to_pandas.return_value = mixed_df
    report.correctness_by_topic.return_value = by_topic_df
    report.failures = failures_df

    payload = _serialise_report(report)

    json.dumps(payload, allow_nan=False)

    assert payload["report"]["correctness_reason"]["0"] is None
    assert payload["report"]["correctness_reason"]["1"] == "Wrong answer"
    assert payload["correct_by_topic"]["score"]["topic_b"] is None
    assert payload["failures"]["reason"]["0"] is None


@pytest.mark.unit
def test_serialise_report_preserves_shape_for_clean_dataframes():
    """When DataFrames have no NaN, serialisation matches the legacy to_dict shape."""
    from server.app.api.v1.endpoints.testbed import _serialise_report

    report = MagicMock()
    report.to_pandas.return_value = pd.DataFrame({"q": ["Q1"], "ok": [True]})
    report.correctness_by_topic.return_value = pd.DataFrame({"score": [0.9]}, index=["t"])
    report.failures = pd.DataFrame()

    payload = _serialise_report(report)

    assert payload["report"] == {"q": {"0": "Q1"}, "ok": {"0": True}}
    assert payload["correct_by_topic"] == {"score": {"t": 0.9}}
    assert payload["failures"] == {}


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
# POST /testbed/testset_generate — multi-file question distribution
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_generate_testset_no_files_returns_422(app_client, auth_headers):
    """FastAPI rejects the request when no files are attached."""
    resp = await app_client.post(
        "/v1/testbed/testset_generate",
        data={"name": "Test", "ll_model": "openai/gpt-4o", "embed_model": "openai/embed", "questions": "5"},
        files=[],
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", ""),
        ("name", "x" * 256),
        ("questions", "0"),
        ("questions", "-1"),
    ],
)
async def test_generate_testset_rejects_invalid_form_fields(app_client, auth_headers, field, value):
    """Empty/oversized names and non-positive question counts must fail validation up front."""
    data = {"name": "Test", "ll_model": "openai/gpt-4o", "embed_model": "openai/embed", "questions": "2"}
    data[field] = value
    pdf_bytes = b"%PDF-1.4\n%fake\n"

    with patch("server.app.api.v1.endpoints.testbed._load_file_chunks", new_callable=AsyncMock) as mock_load:
        resp = await app_client.post(
            "/v1/testbed/testset_generate",
            data=data,
            files=[("files", ("a.pdf", io.BytesIO(pdf_bytes), "application/pdf"))],
            headers=auth_headers,
        )

    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["body", field]
    mock_load.assert_not_awaited()


def _mock_load_chunks_factory(per_file_results):
    """Return an AsyncMock that yields pre-scripted ``_load_file_chunks`` results in order."""
    iterator = iter(per_file_results)

    async def _side_effect(file, temp_directory, embed_config):
        filename, disk_path, reason = next(iterator)
        # consume the upload body so downstream assertions aren't tripped by unread streams
        await file.read()
        return filename, disk_path, reason

    return AsyncMock(side_effect=_side_effect)


@pytest.mark.unit
@pytest.mark.anyio
async def test_generate_testset_distributes_questions(app_client, auth_headers):
    """Questions are distributed across files, not duplicated per file."""
    mock_process = AsyncMock()
    mock_qa_data = {"qa_data": [{"question": "Q1"}, {"question": "Q2"}, {"question": "Q3"}]}
    mock_load = _mock_load_chunks_factory(
        [
            ("a.pdf", Path("/tmp/a.pdf"), None),
            ("b.pdf", Path("/tmp/b.pdf"), None),
            ("c.pdf", Path("/tmp/c.pdf"), None),
        ]
    )

    with (
        patch("server.app.api.v1.endpoints.testbed.get_oci_profile", return_value=None),
        patch("server.app.api.v1.endpoints.testbed.get_giskard_config", return_value={}),
        patch("server.app.api.v1.endpoints.testbed.LiteLlmModelSpec"),
        patch("server.app.api.v1.endpoints.testbed.ModelIdentity"),
        patch("server.app.api.v1.endpoints.testbed.get_temp_directory"),
        patch("server.app.api.v1.endpoints.testbed._load_file_chunks", mock_load),
        patch("server.app.api.v1.endpoints.testbed._process_pdf_file", mock_process),
        patch(
            "server.app.api.v1.endpoints.testbed._store_generated_testset", new_callable=AsyncMock, return_value="AA"
        ),
        patch("server.app.api.v1.endpoints.testbed.get_testset_qa", new_callable=AsyncMock, return_value=mock_qa_data),
    ):
        resp = await app_client.post(
            "/v1/testbed/testset_generate",
            data={"name": "Test", "ll_model": "openai/gpt-4o", "embed_model": "openai/embed", "questions": "7"},
            files=[
                ("files", ("a.pdf", io.BytesIO(b"%PDF-"), "application/pdf")),
                ("files", ("b.pdf", io.BytesIO(b"%PDF-"), "application/pdf")),
                ("files", ("c.pdf", io.BytesIO(b"%PDF-"), "application/pdf")),
            ],
            headers=auth_headers,
        )
    assert resp.status_code == 200
    assert mock_process.await_count == 3
    # 7 questions across 3 files: 3, 2, 2 — `questions` is positional arg index 5
    q_per_file = [call.args[5] for call in mock_process.call_args_list]
    assert q_per_file == [3, 2, 2]
    assert sum(q_per_file) == 7
    assert [call.args[0] for call in mock_process.call_args_list] == [
        Path("/tmp/a.pdf"),
        Path("/tmp/b.pdf"),
        Path("/tmp/c.pdf"),
    ]
    assert resp.json()["rejected_files"] == []


@pytest.mark.unit
@pytest.mark.anyio
async def test_generate_testset_enforces_min_one_per_file(app_client, auth_headers):
    """When questions < files, each file still gets at least 1 question."""
    mock_process = AsyncMock()
    mock_qa_data = {"qa_data": [{"question": "Q1"}, {"question": "Q2"}, {"question": "Q3"}]}
    mock_load = _mock_load_chunks_factory(
        [
            ("a.pdf", Path("/tmp/a.pdf"), None),
            ("b.pdf", Path("/tmp/b.pdf"), None),
            ("c.pdf", Path("/tmp/c.pdf"), None),
        ]
    )

    with (
        patch("server.app.api.v1.endpoints.testbed.get_oci_profile", return_value=None),
        patch("server.app.api.v1.endpoints.testbed.get_giskard_config", return_value={}),
        patch("server.app.api.v1.endpoints.testbed.LiteLlmModelSpec"),
        patch("server.app.api.v1.endpoints.testbed.ModelIdentity"),
        patch("server.app.api.v1.endpoints.testbed.get_temp_directory"),
        patch("server.app.api.v1.endpoints.testbed._load_file_chunks", mock_load),
        patch("server.app.api.v1.endpoints.testbed._process_pdf_file", mock_process),
        patch(
            "server.app.api.v1.endpoints.testbed._store_generated_testset", new_callable=AsyncMock, return_value="AA"
        ),
        patch("server.app.api.v1.endpoints.testbed.get_testset_qa", new_callable=AsyncMock, return_value=mock_qa_data),
    ):
        resp = await app_client.post(
            "/v1/testbed/testset_generate",
            data={"name": "Test", "ll_model": "openai/gpt-4o", "embed_model": "openai/embed", "questions": "1"},
            files=[
                ("files", ("a.pdf", io.BytesIO(b"%PDF-"), "application/pdf")),
                ("files", ("b.pdf", io.BytesIO(b"%PDF-"), "application/pdf")),
                ("files", ("c.pdf", io.BytesIO(b"%PDF-"), "application/pdf")),
            ],
            headers=auth_headers,
        )
    assert resp.status_code == 200
    assert mock_process.await_count == 3
    q_per_file = [call.args[5] for call in mock_process.call_args_list]
    assert q_per_file == [1, 1, 1]


@pytest.mark.unit
@pytest.mark.anyio
async def test_generate_testset_rejects_small_file_and_proceeds(app_client, auth_headers):
    """Files below MIN_CHUNKS_PER_FILE are skipped and reported; accepted files still run."""
    mock_process = AsyncMock()
    mock_qa_data = {"qa_data": [{"question": "Q1"}, {"question": "Q2"}]}
    mock_load = _mock_load_chunks_factory(
        [
            (
                "small.pdf",
                Path("/tmp/small.pdf"),
                "Extracted only 3 text chunks; at least 10 are required to generate a testset.",
            ),
            ("big.pdf", Path("/tmp/big.pdf"), None),
        ]
    )

    with (
        patch("server.app.api.v1.endpoints.testbed.get_oci_profile", return_value=None),
        patch("server.app.api.v1.endpoints.testbed.get_giskard_config", return_value={}),
        patch("server.app.api.v1.endpoints.testbed.LiteLlmModelSpec"),
        patch("server.app.api.v1.endpoints.testbed.ModelIdentity"),
        patch("server.app.api.v1.endpoints.testbed.get_temp_directory"),
        patch("server.app.api.v1.endpoints.testbed._load_file_chunks", mock_load),
        patch("server.app.api.v1.endpoints.testbed._process_pdf_file", mock_process),
        patch(
            "server.app.api.v1.endpoints.testbed._store_generated_testset", new_callable=AsyncMock, return_value="AA"
        ),
        patch("server.app.api.v1.endpoints.testbed.get_testset_qa", new_callable=AsyncMock, return_value=mock_qa_data),
    ):
        resp = await app_client.post(
            "/v1/testbed/testset_generate",
            data={"name": "Test", "ll_model": "openai/gpt-4o", "embed_model": "openai/embed", "questions": "4"},
            files=[
                ("files", ("small.pdf", io.BytesIO(b"%PDF-"), "application/pdf")),
                ("files", ("big.pdf", io.BytesIO(b"%PDF-"), "application/pdf")),
            ],
            headers=auth_headers,
        )
    assert resp.status_code == 200
    # Only the accepted file was processed; its question count is the full ask.
    assert mock_process.await_count == 1
    assert mock_process.call_args_list[0].args[0] == Path("/tmp/big.pdf")
    assert mock_process.call_args_list[0].args[5] == 4
    payload = resp.json()
    assert len(payload["rejected_files"]) == 1
    assert payload["rejected_files"][0]["filename"] == "small.pdf"
    assert "text chunks" in payload["rejected_files"][0]["reason"]


@pytest.mark.unit
@pytest.mark.anyio
async def test_load_file_chunks_same_name_no_overwrite(tmp_path):
    """Two uploads sharing a basename must resolve to distinct bytes on disk.

    Each upload is staged in its own sub-directory so a second upload with
    the same basename does not overwrite the first.
    """
    from fastapi import UploadFile

    from server.app.api.v1.endpoints import testbed as testbed_mod

    bytes_a = b"PDF-CONTENT-A"
    bytes_b = b"PDF-CONTENT-B"
    file_a = UploadFile(filename="dup.pdf", file=io.BytesIO(bytes_a))
    file_b = UploadFile(filename="dup.pdf", file=io.BytesIO(bytes_b))

    # load_and_split is mocked so the validator only cares about the count.
    with patch.object(testbed_mod, "load_and_split", return_value=[object()] * 20):
        name_a, path_a, reason_a = await testbed_mod._load_file_chunks(file_a, tmp_path, {})
        name_b, path_b, reason_b = await testbed_mod._load_file_chunks(file_b, tmp_path, {})

    assert reason_a is None and reason_b is None
    assert name_a == "dup.pdf" and name_b == "dup.pdf"
    assert path_a != path_b, "Same-named uploads must resolve to distinct disk paths"
    assert path_a.read_bytes() == bytes_a
    assert path_b.read_bytes() == bytes_b


@pytest.mark.unit
@pytest.mark.anyio
async def test_generate_testset_all_rejected_returns_400(app_client, auth_headers):
    """If every file is below the chunk floor, the endpoint returns 400 with the rejection list."""
    mock_process = AsyncMock()
    mock_load = _mock_load_chunks_factory(
        [
            (
                "tiny1.pdf",
                Path("/tmp/tiny1.pdf"),
                "Extracted only 1 text chunks; at least 10 are required to generate a testset.",
            ),
            (
                "tiny2.pdf",
                Path("/tmp/tiny2.pdf"),
                "Extracted only 2 text chunks; at least 10 are required to generate a testset.",
            ),
        ]
    )

    with (
        patch("server.app.api.v1.endpoints.testbed.get_oci_profile", return_value=None),
        patch("server.app.api.v1.endpoints.testbed.get_giskard_config", return_value={}),
        patch("server.app.api.v1.endpoints.testbed.LiteLlmModelSpec"),
        patch("server.app.api.v1.endpoints.testbed.ModelIdentity"),
        patch("server.app.api.v1.endpoints.testbed.get_temp_directory"),
        patch("server.app.api.v1.endpoints.testbed._load_file_chunks", mock_load),
        patch("server.app.api.v1.endpoints.testbed._process_pdf_file", mock_process),
    ):
        resp = await app_client.post(
            "/v1/testbed/testset_generate",
            data={"name": "Test", "ll_model": "openai/gpt-4o", "embed_model": "openai/embed", "questions": "4"},
            files=[
                ("files", ("tiny1.pdf", io.BytesIO(b"%PDF-"), "application/pdf")),
                ("files", ("tiny2.pdf", io.BytesIO(b"%PDF-"), "application/pdf")),
            ],
            headers=auth_headers,
        )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "No uploaded files contained enough text" in detail["message"]
    rejected = detail["rejected_files"]
    assert {r["filename"] for r in rejected} == {"tiny1.pdf", "tiny2.pdf"}
    mock_process.assert_not_awaited()


# ---------------------------------------------------------------------------
# Filename sanitisation — canonical tests live in tests/core/test_file_utils.py
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
@pytest.mark.parametrize(
    "traversal_name,expected_basename",
    [
        ("../../../up/file", "file"),
        ("/abs/launch.py", "launch.py"),
        ("subdir/../sibling.pdf", "sibling.pdf"),
    ],
)
async def test_load_file_chunks_uses_upload_basename(tmp_path, traversal_name, expected_basename):
    """Testbed uploads with path-like filenames stay inside temp_directory.

    `_load_file_chunks` runs the upload's filename through `safe_filename()`;
    this test asserts the saved disk_path is under a staging sub-directory
    of temp_directory and uses the expected basename.
    """
    from fastapi import UploadFile

    from server.app.api.v1.endpoints import testbed as testbed_mod

    payload = b"%PDF-sample-payload"
    upload = UploadFile(filename=traversal_name, file=io.BytesIO(payload))
    with patch.object(testbed_mod, "load_and_split", return_value=[object()] * 20):
        _name, disk_path, reason = await testbed_mod._load_file_chunks(upload, tmp_path, {})

    assert reason is None
    assert disk_path.name == expected_basename
    resolved_disk = disk_path.resolve()
    resolved_root = tmp_path.resolve()
    assert resolved_disk.is_relative_to(resolved_root), f"Resolved path escaped temp_directory: {resolved_disk}"
    assert disk_path.read_bytes() == payload


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


@pytest.mark.unit
@pytest.mark.anyio
async def test_generate_testset_db_unavailable_fails_fast(app_client, auth_headers):
    """Returns 503 immediately (before any LLM work) when CORE DB is unavailable."""
    mock_process = AsyncMock()
    with (
        patch("server.app.api.v1.endpoints.testbed.get_core_pool", return_value=None),
        patch("server.app.api.v1.endpoints.testbed._process_pdf_file", mock_process),
    ):
        resp = await app_client.post(
            "/v1/testbed/testset_generate",
            data={"name": "Test", "ll_model": "openai/gpt-4o", "embed_model": "openai/embed", "questions": "2"},
            files=[("files", ("a.pdf", io.BytesIO(b"%PDF-"), "application/pdf"))],
            headers=auth_headers,
        )
    assert resp.status_code == 503
    mock_process.assert_not_awaited()


# ---------------------------------------------------------------------------
# Fallback response details
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.anyio
async def test_generate_testset_api_error_returns_fallback_detail(app_client, auth_headers):
    """Model API errors return the configured fallback detail."""
    from litellm.exceptions import APIConnectionError

    api_err = APIConnectionError(
        message="marker-alpha marker-beta marker-gamma",
        llm_provider="openai",
        model="gpt-4o",
    )
    mock_load = _mock_load_chunks_factory([("a.pdf", Path("/tmp/a.pdf"), None)])
    with (
        patch("server.app.api.v1.endpoints.testbed.get_oci_profile", return_value=None),
        patch("server.app.api.v1.endpoints.testbed.get_giskard_config", return_value={}),
        patch("server.app.api.v1.endpoints.testbed.LiteLlmModelSpec"),
        patch("server.app.api.v1.endpoints.testbed.ModelIdentity"),
        patch("server.app.api.v1.endpoints.testbed.get_temp_directory"),
        patch("server.app.api.v1.endpoints.testbed._load_file_chunks", mock_load),
        patch("server.app.api.v1.endpoints.testbed._process_pdf_file", side_effect=api_err),
    ):
        resp = await app_client.post(
            "/v1/testbed/testset_generate",
            data={"name": "T", "ll_model": "openai/gpt-4o", "embed_model": "openai/embed", "questions": "1"},
            files=[("files", ("a.pdf", io.BytesIO(b"%PDF-"), "application/pdf"))],
            headers=auth_headers,
        )
    assert resp.status_code == 424
    detail = resp.json()["detail"]
    assert detail
    for token in ("marker-alpha", "marker-beta", "marker-gamma"):
        assert token not in detail


@pytest.mark.unit
@pytest.mark.anyio
async def test_generate_testset_value_error_returns_fallback_detail(app_client, auth_headers):
    """ValueError paths return the configured fallback detail."""
    raised = ValueError("marker-alpha marker-beta marker-gamma")
    mock_load = _mock_load_chunks_factory([("a.pdf", Path("/tmp/a.pdf"), None)])
    with (
        patch("server.app.api.v1.endpoints.testbed.get_oci_profile", return_value=None),
        patch("server.app.api.v1.endpoints.testbed.get_giskard_config", return_value={}),
        patch("server.app.api.v1.endpoints.testbed.LiteLlmModelSpec"),
        patch("server.app.api.v1.endpoints.testbed.ModelIdentity"),
        patch("server.app.api.v1.endpoints.testbed.get_temp_directory"),
        patch("server.app.api.v1.endpoints.testbed._load_file_chunks", mock_load),
        patch("server.app.api.v1.endpoints.testbed._process_pdf_file", side_effect=raised),
    ):
        resp = await app_client.post(
            "/v1/testbed/testset_generate",
            data={"name": "T", "ll_model": "openai/gpt-4o", "embed_model": "openai/embed", "questions": "1"},
            files=[("files", ("a.pdf", io.BytesIO(b"%PDF-"), "application/pdf"))],
            headers=auth_headers,
        )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail
    for token in ("marker-alpha", "marker-beta", "marker-gamma"):
        assert token not in detail
