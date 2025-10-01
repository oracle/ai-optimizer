"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore docos

import json
from urllib.parse import urlparse
from pathlib import Path
import shutil

from fastapi import APIRouter, HTTPException, Response, Header, UploadFile
from fastapi.responses import JSONResponse
from pydantic import HttpUrl
import requests

import server.api.core.oci as core_oci

import server.api.utils.databases as utils_databases
import server.api.utils.embed as utils_embed
import server.api.utils.models as utils_models

from common import functions, schema, logging_config

logger = logging_config.logging.getLogger("api.v1.embed")

auth = APIRouter()


@auth.delete(
    "/{vs}",
    description="Drop Vector Store",
)
async def embed_drop_vs(
    vs: schema.VectorStoreTableType,
    client: schema.ClientIdType = Header(default="server"),
) -> JSONResponse:
    """Drop Vector Storage"""
    logger.debug("Received %s embed_drop_vs: %s", client, vs)
    try:
        client_db = utils_databases.get_client_database(client)
        db_conn = utils_databases.connect(client_db)
        utils_databases.drop_vs(db_conn, vs)
    except utils_databases.DbException as ex:
        raise HTTPException(status_code=400, detail=f"Embed: {str(ex)}.") from ex
    return JSONResponse(status_code=200, content={"message": f"Vector Store: {vs} dropped."})


@auth.post(
    "/sql/store",
    description="Store SQL field for Embedding.",
)
async def store_sql_file(
    request: list[str],
    client: schema.ClientIdType = Header(default="server"),
) -> Response:
    """Store contents from a SQL """
    logger.debug("Received store_SQL_data - request: %s", request)
    
    temp_directory = utils_embed.get_temp_directory(client, "embedding")
    result_file = functions.run_sql_query(db_conn=request[0], query=request[1], base_path=temp_directory)

    stored_files= [result_file]
    logger.debug(f"sql ingest - temp csv file location: {result_file}")
    return Response(content=json.dumps(stored_files), media_type="application/json")

@auth.post(
    "/web/store",
    description="Store Web Files for Embedding.",
)
async def store_web_file(
    request: list[HttpUrl],
    client: schema.ClientIdType = Header(default="server"),
) -> Response:
    """Store contents from a web URL"""
    logger.debug("Received store_web_file - request: %s", request)
    temp_directory = utils_embed.get_temp_directory(client, "embedding")

    # Save the file temporarily
    for url in request:
        filename = Path(urlparse(str(url)).path).name
        request_timeout = 60
        logger.debug("Requesting: %s (timeout in %is)", url, request_timeout)
        response = requests.get(url, timeout=request_timeout)
        content_type = response.headers.get("Content-Type", "").lower()

        if "application/pdf" in content_type or "application/octet-stream" in content_type:
            with open(temp_directory / filename, "wb") as file:
                file.write(response.content)
        elif "text" in content_type or "html" in content_type:
            with open(temp_directory / filename, "w", encoding="utf-8") as file:
                file.write(response.text)
        else:
            shutil.rmtree(temp_directory)
            raise HTTPException(
                status_code=500,
                detail=f"Unprocessable content type: {content_type}.",
            )

    stored_files = [f.name for f in temp_directory.iterdir() if f.is_file()]
    return Response(content=json.dumps(stored_files), media_type="application/json")


@auth.post(
    "/local/store",
    description="Store Local Files for Embedding.",
)
async def store_local_file(
    files: list[UploadFile],
    client: schema.ClientIdType = Header(default="server"),
) -> Response:
    """Store contents from a local file uploaded to streamlit"""
    logger.debug("Received store_local_file - files: %s", files)
    temp_directory = utils_embed.get_temp_directory(client, "embedding")
    for file in files:
        filename = temp_directory / file.filename
        file_content = await file.read()
        with filename.open("wb") as file:
            file.write(file_content)

    stored_files = [f.name for f in temp_directory.iterdir() if f.is_file()]
    return Response(content=json.dumps(stored_files), media_type="application/json")


@auth.post(
    "/",
    description="Split and Embed Corpus.",
)
async def split_embed(
    request: schema.DatabaseVectorStorage,
    rate_limit: int = 0,
    client: schema.ClientIdType = Header(default="server"),
) -> Response:
    """Perform Split and Embed"""
    logger.debug("Received split_embed - rate_limit: %i; request: %s", rate_limit, request)
    oci_config = core_oci.get_oci(client=client)
    temp_directory = utils_embed.get_temp_directory(client, "embedding")

    try:
        files = [f for f in temp_directory.iterdir() if f.is_file()]
        logger.info("Processing Files: %s", files)
    except FileNotFoundError as ex:
        raise HTTPException(
            status_code=404,
            detail=f"Embed: Client {client} documents folder not found.",
        ) from ex
    if not files:
        raise HTTPException(
            status_code=404,
            detail=f"Embed: Client {client} no files found in folder.",
        )
    try:
        split_docos, _ = utils_embed.load_and_split_documents(
            files,
            request.model,
            request.chunk_size,
            request.chunk_overlap,
            write_json=False,
            output_dir=None,
        )

        embed_client = utils_models.get_client_embed({"model": request.model, "enabled": True}, oci_config)

        # Calculate and set the vector_store name using get_vs_table
        request.vector_store, _ = functions.get_vs_table(**request.model_dump(exclude={"database", "vector_store"}))

        utils_embed.populate_vs(
            vector_store=request,
            db_details=utils_databases.get_client_database(client),
            embed_client=embed_client,
            input_data=split_docos,
            rate_limit=rate_limit,
        )
        return Response(
            content=json.dumps({"message": f"{len(split_docos)} chunks embedded."}), media_type="application/json"
        )
    except ValueError as ex:
        raise HTTPException(status_code=500, detail=str(ex)) from ex
    except RuntimeError as ex:
        raise HTTPException(status_code=500, detail=str(ex)) from ex
    except Exception as ex:
        logger.error("An exception occurred: %s", ex)
        raise HTTPException(status_code=500, detail="Unexpected Error.") from ex
    finally:
        shutil.rmtree(temp_directory)  # Clean up the temporary directory
