"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Testbed endpoints — manage test sets, generate Q&A from PDFs, and run evaluations.
"""
# spell-checker:ignore giskard testset litellm testsets

import asyncio
import json
import logging
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Annotated, Optional

import pandas as pd
from fastapi import (
    APIRouter,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi import Path as PathParam
from litellm.exceptions import APIConnectionError
from pydantic import ValidationError

from server.app.api.v1.endpoints._helpers import _safe_filename_or_400
from server.app.api.v1.endpoints.chat import get_orchestrator
from server.app.api.v1.schemas.chat import MessageResponse
from server.app.api.v1.schemas.common import ClientId
from server.app.api.v1.schemas.testbed import Evaluation, EvaluationReport, QASetData, QASets, RejectedFile
from server.app.core.error_detail import response_error_detail
from server.app.core.file_utils import get_temp_directory
from server.app.core.settings import resolve_client
from server.app.database.config import get_core_pool
from server.app.mcp.prompts.registry import find_prompt
from server.app.mcp.tools.schemas import get_oci_profile
from server.app.models.litellm_utils import LiteLlmModelSpec
from server.app.models.schemas import ModelIdentity
from server.app.runtime.common import llm_error_detail
from server.app.testbed.database import (
    delete_testset,
    get_evaluations,
    get_testset_qa,
    get_testsets,
    insert_evaluation,
    process_report,
    upsert_qa,
)
from server.app.testbed.generation import (
    _TESTBED_LOCK,
    MIN_CHUNKS_PER_FILE,
    generate_qa_records,
    jsonl_to_json_content,
    load_and_split,
)
from server.app.testbed.metrics import build_evaluation_suite
from server.app.testbed.schemas import EvalId, QARecord, QuestionCount, TestsetId, TestsetName

LOGGER = logging.getLogger(__name__)

auth = APIRouter(prefix="/testbed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_core_pool():
    """Resolve the CORE database pool, raising 503 if unavailable."""
    pool = get_core_pool()
    if not pool:
        raise HTTPException(status_code=503, detail="CORE database is not available")
    return pool


def _get_litellm_config(model_key: str, client: str) -> dict:
    """Resolve a configured model into LiteLLM request parameters."""
    identity = ModelIdentity.from_key(model_key)
    oci_profile = get_oci_profile(client)
    return LiteLlmModelSpec.from_model_identity(identity, oci_profile).to_litellm_kwargs()


# ---------------------------------------------------------------------------
# GET endpoints
# ---------------------------------------------------------------------------


@auth.get("/testsets", response_model=list[QASets])
async def list_testsets():
    """Get all stored testsets."""
    pool = _require_core_pool()
    async with pool.acquire() as conn:
        return await get_testsets(conn)


@auth.get("/evaluations", response_model=list[Evaluation])
async def list_evaluations(tid: Annotated[TestsetId, Query()]):
    """Get evaluations for a testset."""
    pool = _require_core_pool()
    async with pool.acquire() as conn:
        return await get_evaluations(conn, tid.upper())


@auth.get("/evaluation", response_model=EvaluationReport)
async def get_evaluation(eid: Annotated[EvalId, Query()]):
    """Get a single evaluation report."""
    pool = _require_core_pool()
    async with pool.acquire() as conn:
        result = await process_report(conn, eid.upper())
    if not result:
        raise HTTPException(status_code=404, detail=f"Evaluation not found: {eid}")
    return result


@auth.get("/testset_qa", response_model=QASetData)
async def get_testset_qa_endpoint(tid: Annotated[TestsetId, Query()]):
    """Get Q&A data for a testset."""
    pool = _require_core_pool()
    async with pool.acquire() as conn:
        return await get_testset_qa(conn, tid.upper())


# ---------------------------------------------------------------------------
# DELETE endpoint
# ---------------------------------------------------------------------------


@auth.delete("/testset_delete/{tid}", response_model=MessageResponse)
async def delete_testset_endpoint(tid: Annotated[TestsetId, PathParam()]):
    """Delete a testset and its Q&A records."""
    pool = _require_core_pool()
    async with pool.acquire() as conn:
        await delete_testset(conn, tid.upper())
    return MessageResponse(message=f"TestSet: {tid} deleted.")


# ---------------------------------------------------------------------------
# POST endpoints
# ---------------------------------------------------------------------------


@auth.post("/testset_load", response_model=QASetData)
async def upload_testset(
    files: Annotated[list[UploadFile], File()],
    name: Annotated[TestsetName, Form()],
    tid: Annotated[Optional[TestsetId], Form()] = None,
):
    """Upload JSONL/JSON files to create or update a testset."""
    created = datetime.now().isoformat()
    pool = _require_core_pool()

    all_qa: list[dict] = []
    for file in files:
        file_content = await file.read()
        try:
            content = jsonl_to_json_content(file_content)
            parsed = json.loads(content)
        except (ValueError, UnicodeDecodeError) as ex:
            raise HTTPException(
                status_code=400,
                detail=f"Could not parse '{file.filename}' as JSON or JSONL.",
            ) from ex
        items = parsed if isinstance(parsed, list) else [parsed]
        for idx, item in enumerate(items):
            try:
                QARecord.model_validate(item)
            except ValidationError as ex:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "message": f"Invalid QA record at index {idx} in '{file.filename}'.",
                        "errors": ex.errors(include_url=False, include_input=False),
                    },
                ) from ex
            all_qa.append(item)

    try:
        async with pool.acquire() as conn:
            db_id = await upsert_qa(conn, name, created, json.dumps(all_qa), tid)
            await conn.commit()
    except Exception as ex:
        LOGGER.error("An exception occurred: %s", ex)
        raise HTTPException(status_code=500, detail="Unexpected Error.") from ex

    async with pool.acquire() as conn:
        return await get_testset_qa(conn, db_id)


@auth.post("/testset_generate", response_model=QASetData)
async def generate_testset_endpoint(
    files: Annotated[list[UploadFile], File()],
    name: Annotated[TestsetName, Form()],
    ll_model: Annotated[str, Form()],
    embed_model: Annotated[str, Form()],
    questions: Annotated[QuestionCount, Form()] = 2,
    client: Annotated[ClientId, Header()] = "server",
):
    """Generate a Q&A testset from uploaded PDF files."""
    # Fail fast: verify CORE DB is available before starting expensive LLM work.
    pool = _require_core_pool()
    try:
        ll_config = _get_litellm_config(ll_model, client)
        embed_config = _get_litellm_config(embed_model, client)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex

    temp_directory = get_temp_directory(client, "testbed", unique=True)
    full_testsets = temp_directory / "all_testsets.jsonl"

    try:
        if len(files) == 0:
            raise HTTPException(status_code=400, detail="At least one file is required.")

        accepted: list[tuple[str, Path]] = []
        rejected: list[RejectedFile] = []
        for file in files:
            filename, disk_path, reason = await _load_file_chunks(file, temp_directory, embed_config)
            if reason is not None:
                rejected.append(RejectedFile(filename=filename, reason=reason))
            else:
                accepted.append((filename, disk_path))

        if not accepted:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "No uploaded files contained enough text to generate a testset.",
                    "rejected_files": [r.model_dump() for r in rejected],
                },
            )

        num_accepted = len(accepted)
        questions = max(questions, num_accepted)
        base_q, extra = divmod(questions, num_accepted)
        for idx, (_filename, disk_path) in enumerate(accepted):
            file_questions = base_q + (1 if idx < extra else 0)
            await _process_pdf_file(disk_path, embed_config, ll_config, file_questions, full_testsets)
        db_id = await _store_generated_testset(full_testsets, name, pool)
        async with pool.acquire() as conn:
            qa_result = await get_testset_qa(conn, db_id)
        return QASetData(qa_data=qa_result["qa_data"], rejected_files=rejected)

    except ValueError as ex:
        raise HTTPException(
            status_code=400,
            detail=response_error_detail(ex, "Testset generation failed."),
        ) from ex
    except APIConnectionError as ex:
        raise HTTPException(
            status_code=424,
            detail=response_error_detail(ex, "Model API error."),
        ) from ex
    except HTTPException:
        raise
    except Exception as ex:
        LOGGER.error("Unexpected TestSet error: %s", ex)
        raise HTTPException(status_code=500, detail="An unexpected error occurred during testset generation.") from ex
    finally:
        shutil.rmtree(temp_directory, ignore_errors=True)


@auth.post("/evaluate", response_model=EvaluationReport)
async def evaluate_testset(
    tid: Annotated[TestsetId, Query()],
    judge: str,
    client: Annotated[ClientId, Header()] = "server",
):
    """Run an evaluation against a testset using the configured chatbot and judge model."""
    if _TESTBED_LOCK.locked():
        raise HTTPException(
            status_code=409,
            detail="An evaluation is currently running, please retry once complete.",
        )
    evaluated = datetime.now().isoformat()
    cs = resolve_client(client)
    originals = (cs.ll_model.chat_history, cs.vector_search.grade)
    cs.ll_model.chat_history = False
    cs.vector_search.grade = False

    try:
        pool = _require_core_pool()
        qa_records = await _load_testset_from_db(pool, tid)
        judge_config, judge_prompt = _get_judge_config(judge, client)
        try:
            report = await _run_giskard_evaluation(qa_records, client, judge_config, judge_prompt)
        except Exception as ex:
            detail = llm_error_detail(ex)
            raise HTTPException(status_code=502, detail=detail) from ex
        report_payload = _serialise_report(report)

        async with pool.acquire() as conn:
            eid = await insert_evaluation(
                conn,
                tid=tid,
                evaluated=evaluated,
                correctness=report_payload.pop("correctness"),
                settings_json=json.dumps(cs.model_dump(mode="json")),
                rag_report=report_payload,
            )
            await conn.commit()

        async with pool.acquire() as conn:
            result = await process_report(conn, eid)
        if not result:
            raise HTTPException(status_code=500, detail="Failed to load evaluation report after insert")
        return result

    finally:
        cs.ll_model.chat_history, cs.vector_search.grade = originals


# ---------------------------------------------------------------------------
# Internal helpers for POST endpoints
# ---------------------------------------------------------------------------


def _df_to_json_safe(obj) -> dict:
    return json.loads(obj.to_json())


def _serialise_report(report) -> dict:
    """Convert Giskard v3 check results to the persisted testbed report shape."""
    rows = []
    topic_rows = []
    for scenario_result in report.results:
        interaction = scenario_result.final_trace.last
        if interaction is None:
            continue
        inputs = interaction.inputs
        outputs = interaction.outputs
        metadata = interaction.metadata
        check_results = [result for step in scenario_result.steps for result in step.results]
        check_result = check_results[-1] if check_results else None
        correctness = bool(check_result and check_result.passed)
        reason = None if correctness or check_result is None else check_result.message
        record_metadata = metadata.get("metadata", {})
        rows.append(
            {
                "id": metadata.get("id", scenario_result.scenario_name),
                "question": inputs["question"],
                "reference_answer": metadata.get("reference_answer", ""),
                "reference_context": metadata.get("reference_context", ""),
                "conversation_history": metadata.get("conversation_history", []),
                "metadata": record_metadata,
                "agent_answer": outputs["answer"],
                "correctness": correctness,
                "correctness_reason": reason,
            }
        )
        topic_rows.append({"topic": record_metadata.get("topic", "General"), "correctness": correctness})

    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame.set_index("id", inplace=True)
        correct_by_topic = pd.DataFrame(topic_rows).groupby("topic", dropna=False)["correctness"].mean().to_frame()
        failures = frame[~frame["correctness"]]
        correctness = float(frame["correctness"].mean())
    else:
        correct_by_topic = pd.DataFrame(columns=["correctness"])
        failures = frame
        correctness = 0.0
    return {
        "report": _df_to_json_safe(frame),
        "correct_by_topic": _df_to_json_safe(correct_by_topic),
        "failures": _df_to_json_safe(failures) if not failures.empty else {},
        "correctness": correctness,
    }


async def _load_file_chunks(
    file: UploadFile,
    temp_directory: Path,
    embed_config: dict,
) -> tuple[str, Path, Optional[str]]:
    """Save a PDF upload, validate its chunk count, and return the saved path.

    Returns ``(original_filename, saved_path, rejection_reason)``. Accepted
    files are re-split later, one at a time, to keep memory bounded across a
    multi-file request.
    """
    file_content = await file.read()
    if not file.filename:
        raise HTTPException(status_code=400, detail="Uploaded file has no filename.")
    original_name = file.filename
    # Stage each upload in its own sub-directory so two files sharing a basename
    # don't overwrite each other on disk before generation runs.
    file_dir = Path(tempfile.mkdtemp(dir=temp_directory))
    disk_path = file_dir / _safe_filename_or_400(original_name)
    with open(disk_path, "wb") as fh:
        fh.write(file_content)

    chunk_count = len(await asyncio.to_thread(load_and_split, disk_path, embed_config.get("max_chunk_size", 512)))
    if chunk_count < MIN_CHUNKS_PER_FILE:
        return (
            original_name,
            disk_path,
            (
                f"Extracted only {chunk_count} text chunks; at least "
                f"{MIN_CHUNKS_PER_FILE} are required to generate a testset."
            ),
        )
    return original_name, disk_path, None


async def _process_pdf_file(
    disk_path: Path, embed_config: dict, ll_config: dict, questions: int, full_testsets: Path
) -> None:
    """Generate grounded Q&A records from one saved PDF and append them to JSONL."""
    text_nodes = await asyncio.to_thread(load_and_split, disk_path, embed_config.get("max_chunk_size", 512))
    async with _TESTBED_LOCK:
        qa_records = await generate_qa_records(text_nodes, questions, ll_config, embed_config)
    with open(full_testsets, "a", encoding="utf-8") as destination:
        for record in qa_records:
            destination.write(json.dumps(record, ensure_ascii=False) + "\n")


async def _store_generated_testset(full_testsets: Path, name: str, pool) -> str:
    """Read the combined JSONL file and persist the testset in the database."""
    with open(full_testsets, "rb") as fh:
        content = jsonl_to_json_content(fh.read())
    created = datetime.now().isoformat()
    async with pool.acquire() as conn:
        db_id = await upsert_qa(conn, name, created, content)
        await conn.commit()
    return db_id


async def _load_testset_from_db(pool, tid: str) -> list[QARecord]:
    """Load saved Q&A records for Giskard scenario construction."""
    async with pool.acquire() as conn:
        testset_data = await get_testset_qa(conn, tid.upper())
    records = [json.loads(item) if isinstance(item, str) else item for item in testset_data["qa_data"]]
    return [QARecord.model_validate(record) for record in records]


def _get_judge_config(judge: str, client: str) -> tuple[dict, str]:
    """Parse the judge model key, build its config, and retrieve the judge prompt."""
    try:
        judge_config = _get_litellm_config(judge, client)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex
    pc = find_prompt("optimizer_testbed-judge")
    if pc is None:
        raise HTTPException(status_code=500, detail="Testbed judge prompt not found")
    return judge_config, pc.text


async def _run_giskard_evaluation(qa_records, client: str, judge_config: dict, judge_prompt: str):
    """Run the Giskard v3 evaluation suite under the serialization lock."""
    async with _TESTBED_LOCK:
        orchestrator = get_orchestrator()

        async def target(inputs: dict) -> dict:
            result = await orchestrator.execute_chat(
                question=inputs["question"],
                client=client,
            )
            content = result.get("result", "") or ""
            if isinstance(content, dict):
                content = json.dumps(content, default=str)
            return {"answer": content}

        suite = build_evaluation_suite(qa_records, target, judge_config, judge_prompt)
        return await suite.run(parallel=False, return_exception=False, verbose=False)
