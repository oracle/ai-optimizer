"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore docos slugified webscrape

import datetime
import json
from urllib.parse import urlparse
from pathlib import Path
import shutil

from fastapi import APIRouter, HTTPException, Response, Header, UploadFile
from fastapi.responses import JSONResponse
from pydantic import HttpUrl
import aiohttp

import server.api.utils.oci as utils_oci
import server.api.utils.databases as utils_databases
import server.api.utils.embed as utils_embed
import server.api.utils.models as utils_models
import server.api.utils.webscrape as web_parse

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


@auth.get(
    "/{vs}/files",
    description="Get list of files embedded in a Vector Store",
)
async def embed_get_files(
    vs: schema.VectorStoreTableType,
    client: schema.ClientIdType = Header(default="server"),
) -> JSONResponse:
    """Get list of files in Vector Store with statistics"""
    logger.debug("Received %s embed_get_files: %s", client, vs)
    try:
        client_db = utils_databases.get_client_database(client)
        file_list = utils_embed.get_vector_store_files(client_db, vs)
        return JSONResponse(status_code=200, content=file_list)
    except Exception as ex:
        logger.error("Error retrieving file list from %s: %s", vs, str(ex))
        raise HTTPException(status_code=400, detail=f"Could not retrieve file list: {str(ex)}") from ex


@auth.post(
    "/sql/store",
    description="Store SQL field for Embedding.",
)
async def store_sql_file(
    request: list[str],
    client: schema.ClientIdType = Header(default="server"),
) -> Response:
    """Store contents from a SQL"""
    logger.debug("Received store_SQL_data - request: %s", request)

    temp_directory = utils_embed.get_temp_directory(client, "embedding")
    result_file = functions.run_sql_query(db_conn=request[0], query=request[1], base_path=temp_directory)

    stored_files = [result_file]
    logger.debug("sql ingest - temp csv file location: %s", result_file)
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

    async with aiohttp.ClientSession() as session:
        for url in request:
            filename = Path(urlparse(str(url)).path).name
            request_timeout = aiohttp.ClientTimeout(total=60)
            logger.debug("Requesting: %s (timeout in %is)", url, request_timeout)
            async with session.get(str(url), timeout=request_timeout) as response:
                content_type = response.headers.get("Content-Type", "").lower()

                if "application/pdf" in content_type or "application/octet-stream" in content_type:
                    with open(temp_directory / filename, "wb") as file:
                        file.write(await response.read())

                elif "text" in content_type or "html" in content_type:
                    sections = await web_parse.fetch_and_extract_sections(url)
                    base = web_parse.slugify(str(url).rsplit('/', maxsplit=1)[-1]) or "page"
                    out_files = []
                    for idx, sec in enumerate(sections, 1):
                        # filename includes section number and optional slugified title for clarity
                        stub = web_parse.slugify(sec.get("title", "")) or f"{base}-section{idx}"
                        sec_filename = f"{stub}.txt"
                        sec_path = temp_directory / sec_filename
                        with open(sec_path, "w", encoding="utf-8", errors="replace") as f:
                            if sec.get("title"):
                                f.write(sec["title"].strip() + "\n\n")
                            f.write(str(sec["content"]).strip())
                        out_files.append(sec_filename)

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

    # Store file metadata
    file_metadata = {}
    for upload_file in files:
        filename = temp_directory / upload_file.filename
        file_content = await upload_file.read()
        with filename.open("wb") as f:
            f.write(file_content)

        # Capture metadata for this file
        file_metadata[upload_file.filename] = {
            "size": len(file_content),
            "time_modified": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    # Store metadata in JSON file for later use
    metadata_file = temp_directory / ".file_metadata.json"
    with metadata_file.open("w") as f:
        json.dump(file_metadata, f)

    stored_files = [f.name for f in temp_directory.iterdir() if f.is_file() and f.name != ".file_metadata.json"]
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
    oci_config = utils_oci.get(client=client)
    temp_directory = utils_embed.get_temp_directory(client, "embedding")

    try:
        files = [f for f in temp_directory.iterdir() if f.is_file() and f.name != ".file_metadata.json"]
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

    # Load file metadata if available
    file_metadata = None
    metadata_file = temp_directory / ".file_metadata.json"
    if metadata_file.exists():
        try:
            with metadata_file.open("r") as f:
                file_metadata = json.load(f)
            logger.info("Loaded metadata for %d files", len(file_metadata))
        except Exception as ex:
            logger.warning("Could not load file metadata: %s", ex)
            file_metadata = None

    try:
        split_docos, _ = utils_embed.load_and_split_documents(
            files,
            request.model,
            request.chunk_size,
            request.chunk_overlap,
            write_json=False,
            output_dir=None,
            file_metadata=file_metadata,
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


@auth.post(
    "/refresh",
    description="Refresh Vector Store from OCI Bucket.",
)
async def refresh_vector_store(
    request: schema.VectorStoreRefreshRequest,
    client: schema.ClientIdType = Header(default="server"),
) -> JSONResponse:
    """Refresh an existing vector store with new/modified documents from OCI bucket"""
    logger.debug("Received refresh_vector_store - request: %s", request)

    try:
        # Get OCI configuration
        oci_config = utils_oci.get(client=client, auth_profile=request.auth_profile)

        # Get database configuration
        db_details = utils_databases.get_client_database(client)

        # Get existing vector store configuration
        vs_config = utils_embed.get_vector_store_by_alias(db_details, request.vector_store_alias)
        logger.info("Found vector store: %s with model %s", vs_config.vector_store, vs_config.model)

        # Get current bucket objects with metadata
        current_objects = utils_oci.get_bucket_objects_with_metadata(request.bucket_name, oci_config)

        if not current_objects:
            return JSONResponse(
                status_code=200,
                content=schema.VectorStoreRefreshStatus(
                    status="completed",
                    message=f"No supported files found in bucket {request.bucket_name}",
                    processed_files=0,
                    new_files=0,
                    updated_files=0,
                    total_chunks=0,
                ).model_dump(),
            )

        # Get previously processed objects metadata
        processed_objects = utils_embed.get_processed_objects_metadata(db_details, vs_config.vector_store)
        logger.info("Found %d previously processed objects", len(processed_objects))

        # Detect changes
        new_objects, modified_objects = utils_oci.detect_changed_objects(current_objects, processed_objects)
        changed_objects = new_objects + modified_objects

        if not changed_objects:
            # Get total chunks in store
            total_chunks_in_store = utils_embed.get_total_chunks_count(db_details, vs_config.vector_store)

            return JSONResponse(
                status_code=200,
                content=schema.VectorStoreRefreshStatus(
                    status="completed",
                    message="No new or modified files to process",
                    processed_files=0,
                    new_files=0,
                    updated_files=0,
                    total_chunks=0,
                    total_chunks_in_store=total_chunks_in_store,
                ).model_dump(),
            )

        # Get embedding client using the same model as the existing vector store
        embed_client = utils_models.get_client_embed({"model": vs_config.model, "enabled": True}, oci_config)

        # Refresh the vector store
        result = utils_embed.refresh_vector_store_from_bucket(
            vector_store_config=vs_config,
            bucket_name=request.bucket_name,
            bucket_objects=changed_objects,
            db_details=db_details,
            embed_client=embed_client,
            oci_config=oci_config,
            rate_limit=request.rate_limit,
        )

        # Get total chunks in store after refresh
        total_chunks_in_store = utils_embed.get_total_chunks_count(db_details, vs_config.vector_store)

        return JSONResponse(
            status_code=200,
            content=schema.VectorStoreRefreshStatus(
                status="completed",
                message=result.get("message", "Vector store refreshed successfully"),
                processed_files=result.get("processed_files", 0),
                new_files=len(new_objects),
                updated_files=len(modified_objects),
                total_chunks=result.get("total_chunks", 0),
                total_chunks_in_store=total_chunks_in_store,
                errors=result.get("errors", []),
            ).model_dump(),
        )

    except ValueError as ex:
        logger.error("Validation error in refresh_vector_store: %s", ex)
        raise HTTPException(status_code=400, detail=str(ex)) from ex
    except utils_databases.DbException as ex:
        logger.error("Database error in refresh_vector_store: %s", ex)
        raise HTTPException(status_code=500, detail=f"Database error: {str(ex)}") from ex
    except Exception as ex:
        logger.error("Unexpected error in refresh_vector_store: %s", ex)
        raise HTTPException(status_code=500, detail="Unexpected error occurred during refresh") from ex
