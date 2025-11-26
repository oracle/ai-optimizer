"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore testsets testset giskard litellm

import asyncio
import pickle
import shutil

from datetime import datetime
import json
from typing import Optional
from giskard.rag import evaluate, QATestset
from giskard.llm import set_llm_model
from fastapi import APIRouter, HTTPException, Header, UploadFile
from fastapi.responses import JSONResponse
import litellm
from langchain_core.messages import ChatMessage

import server.api.utils.settings as utils_settings
import server.api.utils.oci as utils_oci
import server.api.utils.embed as utils_embed
import server.api.utils.testbed as utils_testbed
import server.api.utils.databases as utils_databases
import server.api.utils.models as utils_models

from server.api.v1 import chat

from common import schema
from common import logging_config

logger = logging_config.logging.getLogger("endpoints.v1.testbed")

auth = APIRouter()


@auth.get(
    "/testsets",
    description="Get Stored TestSets.",
    response_model=list[schema.TestSets],
)
async def testbed_testsets(
    client: schema.ClientIdType = Header(default="server"),
) -> list[schema.TestSets]:
    """Get a list of stored TestSets, create TestSet objects if they don't exist"""
    testsets = utils_testbed.get_testsets(db_conn=utils_databases.get_client_database(client).connection)
    return testsets


@auth.get(
    "/evaluations",
    description="Get Stored Evaluations.",
    response_model=list[schema.Evaluation],
)
async def testbed_evaluations(
    tid: schema.TestSetsIdType,
    client: schema.ClientIdType = Header(default="server"),
) -> list[schema.Evaluation]:
    """Get Evaluations"""
    evaluations = utils_testbed.get_evaluations(
        db_conn=utils_databases.get_client_database(client).connection, tid=tid.upper()
    )
    return evaluations


@auth.get(
    "/evaluation",
    description="Get Stored Single schema.Evaluation.",
    response_model=schema.EvaluationReport,
)
async def testbed_evaluation(
    eid: schema.TestSetsIdType,
    client: schema.ClientIdType = Header(default="server"),
) -> schema.EvaluationReport:
    """Get Evaluations"""
    evaluation = utils_testbed.process_report(
        db_conn=utils_databases.get_client_database(client).connection, eid=eid.upper()
    )
    return evaluation


@auth.get(
    "/testset_qa",
    description="Get Stored schema.TestSets Q&A.",
    response_model=schema.TestSetQA,
)
async def testbed_testset_qa(
    tid: schema.TestSetsIdType,
    client: schema.ClientIdType = Header(default="server"),
) -> schema.TestSetQA:
    """Get TestSet Q&A"""
    return utils_testbed.get_testset_qa(
        db_conn=utils_databases.get_client_database(client).connection, tid=tid.upper()
    )


@auth.delete(
    "/testset_delete/{tid}",
    description="Delete a TestSet",
)
async def testbed_delete_testset(
    tid: Optional[schema.TestSetsIdType] = None,
    client: schema.ClientIdType = Header(default="server"),
) -> JSONResponse:
    """Delete TestSet"""
    utils_testbed.delete_qa(utils_databases.get_client_database(client).connection, tid.upper())
    return JSONResponse(status_code=200, content={"message": f"TestSet: {tid} deleted."})


@auth.post(
    "/testset_load",
    description="Upsert TestSets.",
    response_model=schema.TestSetQA,
)
async def testbed_upsert_testsets(
    files: list[UploadFile],
    name: schema.TestSetsNameType,
    tid: Optional[schema.TestSetsIdType] = None,
    client: schema.ClientIdType = Header(default="server"),
) -> schema.TestSetQA:
    """Update stored TestSet data"""
    created = datetime.now().isoformat()
    db_conn = utils_databases.get_client_database(client).connection
    try:
        for file in files:
            file_content = await file.read()
            content = utils_testbed.jsonl_to_json_content(file_content)
            db_id = utils_testbed.upsert_qa(db_conn, name, created, content, tid)
        db_conn.commit()
    except Exception as ex:
        logger.error("An exception occurred: %s", ex)
        raise HTTPException(status_code=500, detail="Unexpected Error.") from ex

    testset_qa = await testbed_testset_qa(client=client, tid=db_id)
    return testset_qa


async def _process_file_for_testset(
    file, temp_directory, full_testsets, name, questions, ll_model, embed_model, oci_config
):
    """Process a single uploaded file and generate testset"""
    # Read and save file content
    file_content = await file.read()
    filename = temp_directory / file.filename
    logger.info("Writing Q&A File to: %s", filename)
    with open(filename, "wb") as file_handle:
        file_handle.write(file_content)

    # Process file for knowledge base
    text_nodes = utils_testbed.load_and_split(filename)
    test_set = utils_testbed.build_knowledge_base(text_nodes, questions, ll_model, embed_model, oci_config)

    # Save test set
    test_set_filename = temp_directory / f"{name}.jsonl"
    test_set.save(test_set_filename)
    with (
        open(test_set_filename, "r", encoding="utf-8") as source,
        open(full_testsets, "a", encoding="utf-8") as destination,
    ):
        destination.write(source.read())


def _handle_testset_error(ex: Exception, temp_directory, ll_model: str):
    """Handle errors during testset generation"""
    shutil.rmtree(temp_directory)

    if isinstance(ex, KeyError):
        if "None of" in str(ex) and "are in the columns" in str(ex):
            error_message = (
                f"Failed to generate any questions using model '{ll_model}'. "
                "This may indicate the model is unavailable, retired, or not found. "
                "Please verify the model name and try a different model."
            )
            logger.error("TestSet Generation Failed: %s", error_message)
            raise HTTPException(status_code=400, detail=error_message) from ex
        # Re-raise other KeyErrors
        raise ex

    if isinstance(ex, ValueError):
        logger.error("TestSet Validation Error: %s", str(ex))
        raise HTTPException(status_code=400, detail=str(ex)) from ex

    if isinstance(ex, litellm.APIConnectionError):
        logger.error("APIConnectionError Exception: %s", str(ex))
        raise HTTPException(status_code=424, detail=f"Model API error: {str(ex)}") from ex

    logger.error("Unknown TestSet Exception: %s", str(ex))
    raise HTTPException(status_code=500, detail=f"Unexpected TestSet error: {str(ex)}.") from ex


@auth.post(
    "/testset_generate",
    description="Generate Q&A Test Set.",
    response_model=schema.TestSetQA,
)
async def testbed_generate_qa(
    files: list[UploadFile],
    name: schema.TestSetsNameType,
    ll_model: str,
    embed_model: str,
    questions: int = 2,
    client: schema.ClientIdType = Header(default="server"),
) -> schema.TestSetQA:
    """Retrieve contents from a local file uploaded and generate Q&A"""
    # Get the Model Configuration
    try:
        oci_config = utils_oci.get(client)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex

    temp_directory = utils_embed.get_temp_directory(client, "testbed")
    full_testsets = temp_directory / "all_testsets.jsonl"

    for file in files:
        try:
            await _process_file_for_testset(
                file, temp_directory, full_testsets, name, questions, ll_model, embed_model, oci_config
            )
        except (KeyError, ValueError, litellm.APIConnectionError, Exception) as ex:
            _handle_testset_error(ex, temp_directory, ll_model)

    # Store tests in database (only if we successfully generated testsets)
    with open(full_testsets, "rb") as file:
        upload_file = UploadFile(file=file, filename=full_testsets)
        testset_qa = await testbed_upsert_testsets(client=client, files=[upload_file], name=name)
    shutil.rmtree(temp_directory)

    return testset_qa


@auth.post(
    "/evaluate",
    description="Evaluate Q&A Test Set.",
    response_model=schema.EvaluationReport,
)
def testbed_evaluate(
    tid: schema.TestSetsIdType,
    judge: str,
    client: schema.ClientIdType = Header(default="server"),
) -> schema.EvaluationReport:
    """Run evaluate against a testset"""

    def get_answer(question: str):
        """Submit question against the chatbot"""
        request = schema.ChatRequest(
            messages=[ChatMessage(role="human", content=question)],
        )
        ai_response = asyncio.run(chat.chat_post(client=client, request=request))
        return ai_response["choices"][0]["message"]["content"]

    evaluated = datetime.now().isoformat()
    client_settings = utils_settings.get_client(client)
    # Disable History
    client_settings.ll_model.chat_history = False
    # Disable Grade vector_search
    client_settings.vector_search.grade = False

    db_conn = utils_databases.get_client_database(client).connection
    testset = utils_testbed.get_testset_qa(db_conn=db_conn, tid=tid.upper())
    qa_test = "\n".join(json.dumps(item) for item in testset.qa_data)
    temp_directory = utils_embed.get_temp_directory(client, "testbed")

    with open(temp_directory / f"{tid}_output.txt", "w", encoding="utf-8") as file:
        file.write(qa_test)
    loaded_testset = QATestset.load(temp_directory / f"{tid}_output.txt")

    # Setup Judge Model
    logger.debug("Starting evaluation with Judge: %s", judge)
    oci_config = utils_oci.get(client)

    judge_config = utils_models.get_litellm_config(model_config={"model": judge}, oci_config=oci_config, giskard=True)
    set_llm_model(llm_model=judge, **judge_config)
    try:
        report = evaluate(get_answer, testset=loaded_testset, metrics=None)
    except KeyError as ex:
        if str(ex) == "'correctness'":
            raise HTTPException(status_code=500, detail="Unable to determine the correctness; please retry.") from ex

    logger.debug("Ending evaluation with Judge: %s", judge)

    eid = utils_testbed.insert_evaluation(
        db_conn=db_conn,
        tid=tid,
        evaluated=evaluated,
        correctness=report.correctness,
        settings=client_settings.model_dump_json(),
        rag_report=pickle.dumps(report),
    )
    db_conn.commit()
    shutil.rmtree(temp_directory)

    return utils_testbed.process_report(db_conn=db_conn, eid=eid)
