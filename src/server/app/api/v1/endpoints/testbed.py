"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Testbed endpoints — manage test sets, generate Q&A from PDFs, and run evaluations.
"""
# spell-checker:ignore giskard testset litellm testsets

import asyncio
import json
import logging
import pickle
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from giskard.llm import set_llm_model
from giskard.rag import QATestset, evaluate
from giskard.rag.base import AgentAnswer
from litellm.exceptions import APIConnectionError

from server.app.api.v1.endpoints.chat import get_orchestrator
from server.app.api.v1.schemas.chat import MessageResponse
from server.app.api.v1.schemas.testbed import Evaluation, EvaluationReport, QASetData, QASets, RejectedFile
from server.app.core.file_utils import get_temp_directory, safe_filename
from server.app.core.settings import resolve_client
from server.app.database.config import get_core_pool
from server.app.mcp.prompts.registry import find_prompt
from server.app.mcp.tools.schemas import get_oci_profile
from server.app.models.litellm_utils import LiteLlmModelSpec
from server.app.models.schemas import ModelIdentity
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
    _GISKARD_LOCK,
    MIN_CHUNKS_PER_FILE,
    build_knowledge_base,
    get_giskard_config,
    jsonl_to_json_content,
    load_and_split,
)
from server.app.testbed.metrics import CustomCorrectnessMetric

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
async def list_evaluations(tid: str):
    """Get evaluations for a testset."""
    pool = _require_core_pool()
    async with pool.acquire() as conn:
        return await get_evaluations(conn, tid.upper())


@auth.get("/evaluation", response_model=EvaluationReport)
async def get_evaluation(eid: str):
    """Get a single evaluation report."""
    pool = _require_core_pool()
    async with pool.acquire() as conn:
        result = await process_report(conn, eid.upper())
    if not result:
        raise HTTPException(status_code=404, detail=f"Evaluation not found: {eid}")
    return result


@auth.get("/testset_qa", response_model=QASetData)
async def get_testset_qa_endpoint(tid: str):
    """Get Q&A data for a testset."""
    pool = _require_core_pool()
    async with pool.acquire() as conn:
        return await get_testset_qa(conn, tid.upper())


# ---------------------------------------------------------------------------
# DELETE endpoint
# ---------------------------------------------------------------------------


@auth.delete("/testset_delete/{tid}", response_model=MessageResponse)
async def delete_testset_endpoint(tid: str):
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
    files: list[UploadFile] = File(...),
    name: str = Form(),
    tid: Optional[str] = Form(default=None),
):
    """Upload JSONL/JSON files to create or update a testset."""
    created = datetime.now().isoformat()
    pool = _require_core_pool()
    try:
        all_qa = []
        for file in files:
            file_content = await file.read()
            content = jsonl_to_json_content(file_content)
            parsed = json.loads(content)
            if isinstance(parsed, list):
                all_qa.extend(parsed)
            else:
                all_qa.append(parsed)
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
    files: list[UploadFile] = File(...),
    name: str = Form(),
    ll_model: str = Form(),
    embed_model: str = Form(),
    questions: int = Form(default=2),
    client: str = Header(default="server"),
):
    """Generate a Q&A testset from uploaded PDF files."""
    # Fail fast: verify CORE DB is available before starting expensive LLM work.
    pool = _require_core_pool()
    oci_profile = get_oci_profile(client)
    try:
        ll_config = get_giskard_config(
            LiteLlmModelSpec.from_model_identity(ModelIdentity.from_key(ll_model), oci_profile).to_litellm_kwargs(),
            "ll",
        )
        embed_config = get_giskard_config(
            LiteLlmModelSpec.from_model_identity(ModelIdentity.from_key(embed_model), oci_profile).to_litellm_kwargs(),
            "embed",
        )
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex

    temp_directory = get_temp_directory(client, "testbed", unique=True)
    full_testsets = temp_directory / "all_testsets.jsonl"

    try:
        if len(files) == 0:
            raise HTTPException(status_code=400, detail="At least one file is required.")

        accepted: list[tuple[str, list]] = []
        rejected: list[RejectedFile] = []
        for file in files:
            filename, text_nodes, reason = await _load_file_chunks(file, temp_directory, embed_config)
            if reason is not None:
                rejected.append(RejectedFile(filename=filename, reason=reason))
            else:
                accepted.append((filename, text_nodes))

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
        for idx, (_filename, text_nodes) in enumerate(accepted):
            file_questions = base_q + (1 if idx < extra else 0)
            await _process_pdf_file(
                text_nodes, temp_directory, name, embed_config, ll_config, file_questions, full_testsets
            )
        db_id = await _store_generated_testset(full_testsets, name, pool)
        async with pool.acquire() as conn:
            qa_result = await get_testset_qa(conn, db_id)
        return QASetData(qa_data=qa_result["qa_data"], rejected_files=rejected)

    except KeyError as ex:
        if "None of" in str(ex) and "are in the columns" in str(ex):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Failed to generate questions using model '{ll_model}'. "
                    "The model may be unavailable or retired. Please try a different model."
                ),
            ) from ex
        raise
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex
    except APIConnectionError as ex:
        raise HTTPException(status_code=424, detail=f"Model API error: {ex}") from ex
    except HTTPException:
        raise
    except Exception as ex:
        LOGGER.error("Unexpected TestSet error: %s", ex)
        raise HTTPException(status_code=500, detail="An unexpected error occurred during testset generation.") from ex
    finally:
        shutil.rmtree(temp_directory, ignore_errors=True)


@auth.post("/evaluate", response_model=EvaluationReport)
async def evaluate_testset(
    tid: str,
    judge: str,
    client: str = Header(default="server"),
):
    """Run an evaluation against a testset using the configured chatbot and judge model."""
    if _GISKARD_LOCK.locked():
        raise HTTPException(
            status_code=409,
            detail="An evaluation is currently running, please retry once complete.",
        )
    evaluated = datetime.now().isoformat()
    cs = resolve_client(client)
    originals = (cs.ll_model.chat_history, cs.vector_search.grade)
    cs.ll_model.chat_history = False
    cs.vector_search.grade = False

    temp_directory = get_temp_directory(client, "testbed", unique=True)

    try:
        pool = _require_core_pool()
        loaded_testset = await _load_testset_from_db(pool, tid, temp_directory)
        judge_config, judge_prompt = _get_judge_config(judge, client)
        answers = await _collect_answers(loaded_testset, client)
        report = await _run_giskard_evaluation(loaded_testset, answers, judge_config, judge_prompt)

        async with pool.acquire() as conn:
            eid = await insert_evaluation(
                conn,
                tid=tid,
                evaluated=evaluated,
                correctness=report.correctness,
                settings_json=json.dumps(cs.model_dump(mode="json")),
                rag_report=pickle.dumps(report),
            )
            await conn.commit()

        async with pool.acquire() as conn:
            result = await process_report(conn, eid)
        if not result:
            raise HTTPException(status_code=500, detail="Failed to load evaluation report after insert")
        return result

    finally:
        cs.ll_model.chat_history, cs.vector_search.grade = originals
        shutil.rmtree(temp_directory, ignore_errors=True)


# ---------------------------------------------------------------------------
# Internal helpers for POST endpoints
# ---------------------------------------------------------------------------


async def _load_file_chunks(
    file: UploadFile,
    temp_directory: Path,
    embed_config: dict,
) -> tuple[str, list, Optional[str]]:
    """Read a PDF upload, split into chunks, and validate the chunk count.

    Returns ``(original_filename, text_nodes, rejection_reason)``. When
    ``rejection_reason`` is not ``None`` the file should be skipped.
    """
    file_content = await file.read()
    if not file.filename:
        raise HTTPException(status_code=400, detail="Uploaded file has no filename.")
    original_name = file.filename
    disk_path = temp_directory / safe_filename(original_name)
    with open(disk_path, "wb") as fh:
        fh.write(file_content)

    text_nodes = load_and_split(disk_path, embed_config.get("max_chunk_size", 512))
    if len(text_nodes) < MIN_CHUNKS_PER_FILE:
        return (
            original_name,
            [],
            (
                f"Extracted only {len(text_nodes)} text chunks; at least "
                f"{MIN_CHUNKS_PER_FILE} are required to generate a testset."
            ),
        )
    return original_name, text_nodes, None


async def _process_pdf_file(
    text_nodes: list,
    temp_directory: Path,
    name: str,
    embed_config: dict,
    ll_config: dict,
    questions: int,
    full_testsets: Path,
) -> None:
    """Build a Giskard testset from pre-split chunks and append to the combined JSONL."""
    async with _GISKARD_LOCK:
        test_set = await asyncio.to_thread(build_knowledge_base, text_nodes, questions, ll_config, embed_config)

    test_set_filename = temp_directory / safe_filename(f"{name}.jsonl")
    test_set.save(test_set_filename)
    with (
        open(test_set_filename, "r", encoding="utf-8") as source,
        open(full_testsets, "a", encoding="utf-8") as destination,
    ):
        destination.write(source.read())


async def _store_generated_testset(full_testsets: Path, name: str, pool) -> str:
    """Read the combined JSONL file and persist the testset in the database."""
    with open(full_testsets, "rb") as fh:
        content = jsonl_to_json_content(fh.read())
    created = datetime.now().isoformat()
    async with pool.acquire() as conn:
        db_id = await upsert_qa(conn, name, created, content)
        await conn.commit()
    return db_id


async def _load_testset_from_db(pool, tid: str, temp_directory: Path):
    """Load a QATestset from the database via a temporary file."""
    async with pool.acquire() as conn:
        testset_data = await get_testset_qa(conn, tid.upper())
    qa_test = "\n".join(item if isinstance(item, str) else json.dumps(item) for item in testset_data["qa_data"])
    temp_file = temp_directory / f"{tid}_output.txt"
    temp_file.write_text(qa_test, encoding="utf-8")
    return QATestset.load(temp_file)


def _get_judge_config(judge: str, client: str) -> tuple[dict, str]:
    """Parse the judge model key, build its config, and retrieve the judge prompt."""
    oci_profile = get_oci_profile(client)
    try:
        judge_identity = ModelIdentity.from_key(judge)
        judge_config = get_giskard_config(
            LiteLlmModelSpec.from_model_identity(judge_identity, oci_profile).to_litellm_kwargs(), "ll"
        )
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex
    pc = find_prompt("optimizer_testbed-judge")
    if pc is None:
        raise HTTPException(status_code=500, detail="Testbed judge prompt not found")
    return judge_config, pc.text


async def _run_giskard_evaluation(loaded_testset, answers, judge_config: dict, judge_prompt: str):
    """Run Giskard evaluation under the serialization lock."""
    async with _GISKARD_LOCK:
        custom_metric = CustomCorrectnessMetric(
            name="correctness",
            system_prompt=judge_prompt,
            agent_description="A chatbot answering questions.",
        )

        def _run():
            set_llm_model(**judge_config)
            return evaluate(answers, testset=loaded_testset, metrics=[custom_metric])

        try:
            return await asyncio.to_thread(_run)
        except KeyError as ex:
            if str(ex) == "'correctness'":
                raise HTTPException(
                    status_code=500, detail="Unable to determine the correctness; please retry."
                ) from ex
            raise


async def _collect_answers(loaded_testset, client: str) -> list:
    """Collect answers from the chatbot for all questions in the testset."""
    orchestrator = get_orchestrator()
    answers = []
    for sample in loaded_testset.to_pandas().itertuples():
        result = await orchestrator.execute_chat(
            question=sample.question,
            client=client,
        )
        content = result.get("result", "") or ""
        if isinstance(content, dict):
            content = json.dumps(content, default=str)
        answers.append(AgentAnswer(message=content))
    return answers
