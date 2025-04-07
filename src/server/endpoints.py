"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore langgraph, ocid, docos, giskard, testsets, testset, noauth
# spell-checker:ignore astream, ainvoke, litellm

import asyncio
import json
import pickle
from datetime import datetime
from urllib.parse import urlparse
from pathlib import Path
import shutil
from typing import AsyncGenerator, Literal, Optional
import time
import requests
from pydantic import HttpUrl

from langgraph.graph.state import CompiledStateGraph
from langchain_core.messages import HumanMessage, AnyMessage, convert_to_openai_messages, ChatMessage
from langchain_core.runnables import RunnableConfig
from giskard.rag import evaluate, QATestset
from giskard.rag.metrics import correctness_metric
from litellm import APIConnectionError

from fastapi import FastAPI, Header, Query, HTTPException, UploadFile, Response
from fastapi.responses import StreamingResponse, JSONResponse

import server.bootstrap as bootstrap
import server.utils.databases as databases
import server.utils.oci as server_oci
import server.utils.models as models
import server.utils.embedding as embedding
import server.utils.testbed as testbed
import server.agents.chatbot as chatbot

import common.schema as schema
import common.logging_config as logging_config
import common.functions as functions

logger = logging_config.logging.getLogger("server.endpoints")


# Load Models with Definition Data
DATABASE_OBJECTS = bootstrap.database_def.main()
MODEL_OBJECTS = bootstrap.model_def.main()
OCI_OBJECTS = bootstrap.oci_def.main()
PROMPT_OBJECTS = bootstrap.prompt_eng_def.main()
SETTINGS_OBJECTS = bootstrap.settings_def.main()


#####################################################
# Helpers
#####################################################
def get_temp_directory(client: schema.ClientIdType, function: str) -> Path:
    """Return the path to store temporary files"""
    if Path("/app/tmp").exists() and Path("/app/tmp").is_dir():
        client_folder = Path("/app/tmp") / client / function
    else:
        client_folder = Path("/tmp") / client / function
    client_folder.mkdir(parents=True, exist_ok=True)
    logger.debug("Created temporary directory: %s", client_folder)
    return client_folder


def get_client_settings(client: schema.ClientIdType) -> schema.Settings:
    """Return schema.Settings Object based on client ID"""
    client_settings = next((settings for settings in SETTINGS_OBJECTS if settings.client == client), None)
    if not client_settings:
        raise HTTPException(status_code=404, detail=f"Client: {client} not found.")
    return client_settings


def get_client_oci(client: schema.ClientIdType) -> schema.OracleCloudSettings:
    """Return schema.Settings Object based on client ID"""
    auth_profile = "DEFAULT"
    client_settings = get_client_settings(client)
    if client_settings.oci:
        auth_profile = getattr(client_settings.oci, "auth_profile", "DEFAULT")

    return next((oci for oci in OCI_OBJECTS if oci.auth_profile == auth_profile), None)


def get_client_db(client: schema.ClientIdType) -> schema.Database:
    """Return a schema.Database Object based on client settings"""
    db_name = "DEFAULT"
    client_settings = get_client_settings(client)
    if client_settings.rag:
        db_name = getattr(client_settings.rag, "database", "DEFAULT")
        db_obj = next((db for db in DATABASE_OBJECTS if db.name == db_name), None)
        # Refresh the connection if disconnected
        try:
            if db_obj:
                databases.test(db_obj)
        except databases.DbException as ex:
            db_obj.connected = False
            raise HTTPException(status_code=ex.status_code, detail=f"Database: {db_obj.name} {ex.detail}.") from ex

    return db_obj


#####################################################
# Endpoints
#####################################################
def register_endpoints(noauth: FastAPI, auth: FastAPI) -> None:
    """Called by the server startup to load the endpoints"""

    #################################################
    # Kubernetes
    #################################################
    @noauth.get("/v1/liveness")
    async def liveness_probe():
        """Kubernetes liveness probe"""
        return {"status": "alive"}

    @noauth.get("/v1/readiness")
    async def readiness_probe():
        """Kubernetes ready probe"""
        return {"status": "ready"}

    #####################################################
    # databases Endpoints
    #####################################################
    @auth.get("/v1/databases", description="Get all database configurations", response_model=list[schema.Database])
    async def databases_list() -> list[schema.Database]:
        """List all databases"""
        logger.debug("Received databases_list")
        for db in DATABASE_OBJECTS:
            try:
                db_conn = databases.connect(db)
            except databases.DbException as ex:
                logger.debug("Skipping %s - exception: %s", db.name, str(ex))
                continue
            db.vector_stores = embedding.get_vs(db_conn)

        return DATABASE_OBJECTS

    @auth.get(
        "/v1/databases/{name}",
        description="Get single database configuration and vector storage",
        response_model=schema.Database,
    )
    async def databases_get(name: schema.DatabaseNameType) -> schema.Database:
        """Get single database"""
        logger.debug("Received databases_get - name: %s", name)
        db = next((db for db in DATABASE_OBJECTS if db.name == name), None)
        if not db:
            raise HTTPException(status_code=404, detail=f"Database: {name} not found.")
        try:
            db_conn = databases.connect(db)
            db.vector_stores = embedding.get_vs(db_conn)
        except databases.DbException as ex:
            raise HTTPException(status_code=406, detail=f"Database: {name} {str(ex)}.") from ex
        return db

    @auth.patch(
        "/v1/databases/{name}",
        description="Update, Test, Set as default database configuration",
        response_model=schema.Database,
    )
    async def databases_update(name: schema.DatabaseNameType, payload: schema.DatabaseAuth) -> schema.Database:
        """Update schema.Database"""
        logger.debug("Received databases_update - name: %s; payload: %s", name, payload)
        db = next((db for db in DATABASE_OBJECTS if db.name == name), None)
        if not db:
            raise HTTPException(status_code=404, detail=f"Database: {name} not found.")
        try:
            payload.config_dir = db.config_dir
            payload.wallet_location = db.wallet_location
            db_conn = databases.connect(payload)
        except databases.DbException as ex:
            db.connected = False
            raise HTTPException(status_code=ex.status_code, detail=f"Database: {name} {ex.detail}.") from ex
        db.user = payload.user
        db.password = payload.password
        db.dsn = payload.dsn
        db.wallet_password = payload.wallet_password
        db.connected = True
        db.set_connection(db_conn)
        # Unset and disconnect other databases
        for other_db in DATABASE_OBJECTS:
            if other_db.name != name and other_db.connection:
                other_db.set_connection(databases.disconnect(db.connection))
                other_db.connected = False
        return await databases_get(name)

    #################################################
    # embed Endpoints
    #################################################
    @auth.delete("/v1/embed/{vs}", description="Drop Vector Store")
    async def embed_drop_vs(
        vs: schema.VectorStoreTableType, client: schema.ClientIdType = Header(...)
    ) -> JSONResponse:
        """Drop Vector Storage"""
        logger.debug("Received %s embed_drop_vs: %s", client, vs)
        embedding.drop_vs(get_client_db(client).connection, vs)
        return JSONResponse(status_code=200, content={"message": f"Vector Store: {vs} dropped."})

    @auth.post(
        "/v1/embed/web/store",
        description="Store Web Files for Embedding.",
    )
    async def store_web_file(request: list[HttpUrl], client: schema.ClientIdType = Header(...)) -> Response:
        """Store contents from a web URL"""
        logger.debug("Received store_web_file - request: %s", request)
        temp_directory = get_temp_directory(client, "embedding")

        # Save the file temporarily
        for url in request:
            filename = Path(urlparse(str(url)).path).name
            response = requests.get(url, timeout=60)
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
        "/v1/embed/local/store",
        description="Store Local Files for Embedding.",
    )
    async def store_local_file(files: list[UploadFile], client: schema.ClientIdType = Header(...)) -> Response:
        """Store contents from a local file uploaded to streamlit"""
        logger.debug("Received store_local_file - files: %s", files)
        temp_directory = get_temp_directory(client, "embedding")
        for file in files:
            filename = temp_directory / file.filename
            file_content = await file.read()
            with filename.open("wb") as file:
                file.write(file_content)

        stored_files = [f.name for f in temp_directory.iterdir() if f.is_file()]
        return Response(content=json.dumps(stored_files), media_type="application/json")

    @auth.post(
        "/v1/embed",
        description="Split and Embed Corpus.",
    )
    async def split_embed(
        request: schema.DatabaseVectorStorage, rate_limit: int = 0, client: schema.ClientIdType = Header(...)
    ) -> Response:
        """Perform Split and Embed"""
        logger.debug("Received split_embed - rate_limit: %i; request: %s", rate_limit, request)
        oci_config = get_client_oci(client)
        temp_directory = get_temp_directory(client, "embedding")

        try:
            files = [f for f in temp_directory.iterdir() if f.is_file()]
            logger.info("Processing Files: %s", files)
        except FileNotFoundError as ex:
            raise HTTPException(
                status_code=404,
                detail=f"Client: {client} documents folder not found.",
            ) from ex
        if not files:
            raise HTTPException(
                status_code=404,
                detail=f"Client: {client} no files found in folder.",
            )
        try:
            split_docos, _ = embedding.load_and_split_documents(
                files,
                request.model,
                request.chunk_size,
                request.chunk_overlap,
                write_json=False,
                output_dir=None,
            )
            embed_client = await models.get_client(
                MODEL_OBJECTS, {"model": request.model, "rag_enabled": True}, oci_config
            )

            # Calculate and set the vector_store name using get_vs_table
            request.vector_store, _ = functions.get_vs_table(
                **request.model_dump(exclude={"database", "vector_store"})
            )

            embedding.populate_vs(
                vector_store=request,
                db_details=get_client_db(client),
                embed_client=embed_client,
                input_data=split_docos,
                rate_limit=rate_limit,
            )
            return Response(
                content=json.dumps({"message": f"{len(split_docos)} chunks embedded."}), media_type="application/json"
            )
        except ValueError as ex:
            raise HTTPException(status_code=500, detail=str(ex)) from ex
        except Exception as ex:
            logger.error("An exception occurred: %s", ex)
            raise HTTPException(status_code=500, detail="Unexpected Error.") from ex
        finally:
            shutil.rmtree(temp_directory)  # Clean up the temporary directory

    #################################################
    # models Endpoints
    #################################################
    @auth.get("/v1/models", description="Get all models", response_model=list[schema.Model])
    async def models_list(
        model_type: Optional[schema.ModelTypeType] = Query(None),
    ) -> list[schema.Model]:
        """List all models after applying filters if specified"""
        logger.debug("Received models_list - type: %s", model_type)
        models_ret = await models.apply_filter(MODEL_OBJECTS, model_type=model_type)

        return models_ret

    @auth.get("/v1/models/{name:path}", description="Get a single model", response_model=schema.Model)
    async def models_get(name: schema.ModelNameType) -> schema.Model:
        """List a specific model"""
        logger.debug("Received models_get - name: %s", name)
        models_ret = await models.apply_filter(MODEL_OBJECTS, model_name=name)
        if not models_ret:
            raise HTTPException(status_code=404, detail=f"Model: {name} not found.")

        return models_ret[0]

    @auth.patch("/v1/models/{name:path}", description="Update a model", response_model=schema.Model)
    async def models_update(name: schema.ModelNameType, payload: schema.Model) -> schema.Model:
        """Update a model"""
        logger.debug("Received models_update - name: %s; payload: %s", name, payload)

        model_upd = await models_get(name)
        for key, value in payload:
            if hasattr(model_upd, key):
                setattr(model_upd, key, value)
            else:
                raise HTTPException(status_code=404, detail=f"Model: Invalid setting - {key}.")

        return await models_get(name)

    @auth.post("/v1/models", description="Create a model", response_model=schema.Model)
    async def models_create(payload: schema.Model) -> schema.Model:
        """Update a model"""
        logger.debug("Received model_create - payload: %s", payload)
        if any(d.name == payload.name for d in MODEL_OBJECTS):
            raise HTTPException(status_code=409, detail=f"Model: {payload.name} already exists.")
        if not payload.openai_compat:
            openai_compat = next(
                (model_config.openai_compat for model_config in MODEL_OBJECTS if model_config.api == payload.api),
                False,
            )
            payload.openai_compat = openai_compat
        MODEL_OBJECTS.append(payload)

        return await models_get(payload.name)

    @auth.delete("/v1/models/{name:path}", description="Delete a model")
    async def models_delete(name: schema.ModelNameType) -> JSONResponse:
        """Delete a model"""
        logger.debug("Received models_delete - name: %s", name)
        global MODEL_OBJECTS  # pylint: disable=global-statement
        MODEL_OBJECTS = [model for model in MODEL_OBJECTS if model.name != name]

        return JSONResponse(status_code=200, content={"message": f"Model: {name} deleted."})

    #################################################
    # oci Endpoints
    #################################################
    @auth.get("/v1/oci", description="View OCI Configuration", response_model=list[schema.OracleCloudSettings])
    async def oci_list() -> list[schema.OracleCloudSettings]:
        """List OCI Configuration"""
        logger.debug("Received oci_list")
        return OCI_OBJECTS

    @auth.get(
        "/v1/oci/{auth_profile}",
        description="View OCI Profile Configuration",
        response_model=schema.OracleCloudSettings,
    )
    async def oci_get(auth_profile: schema.OCIProfileType) -> schema.OracleCloudSettings:
        """List OCI Configuration"""
        logger.debug("Received oci_get - auth_profile: %s", auth_profile)
        oci_config = next((oci_config for oci_config in OCI_OBJECTS if oci_config.auth_profile == auth_profile), None)
        if not oci_config:
            raise HTTPException(status_code=404, detail=f"OCI: Profile {auth_profile} not found.")
        return oci_config

    @auth.get(
        "/v1/oci/compartments/{auth_profile}",
        description="Get OCI Compartments",
        response_model=dict,
    )
    async def oci_list_compartments(auth_profile: schema.OCIProfileType) -> dict:
        """Return a list of compartments"""
        logger.debug("Received oci_list_compartments - auth_profile: %s", auth_profile)
        oci_config = await oci_get(auth_profile)
        compartments = server_oci.get_compartments(oci_config)
        return compartments

    @auth.get(
        "/v1/oci/buckets/{compartment_ocid}/{auth_profile}",
        description="Get OCI Object Storage buckets in Compartment OCID",
        response_model=list,
    )
    async def oci_list_buckets(auth_profile: schema.OCIProfileType, compartment_ocid: str) -> list:
        """Return a list of buckets; Validate OCID using Pydantic class"""
        logger.debug(
            "Received oci_list_buckets - auth_profile: %s; compartment_ocid: %s", auth_profile, compartment_ocid
        )
        compartment_obj = schema.OracleResource(ocid=compartment_ocid)
        oci_config = await oci_get(auth_profile)
        buckets = server_oci.get_buckets(compartment_obj.ocid, oci_config)
        return buckets

    @auth.get(
        "/v1/oci/objects/{bucket_name}/{auth_profile}",
        description="Get OCI Object Storage buckets objects",
        response_model=list,
    )
    async def oci_list_bucket_objects(auth_profile: schema.OCIProfileType, bucket_name: str) -> list:
        """Return a list of bucket objects; Validate OCID using Pydantic class"""
        logger.debug("Received oci_list_bucket_objects - auth_profile: %s; bucket_name: %s", auth_profile, bucket_name)
        oci_config = await oci_get(auth_profile)
        objects = server_oci.get_bucket_objects(bucket_name, oci_config)
        return objects

    @auth.patch(
        "/v1/oci/{auth_profile}",
        description="Update, Test, Set as Default OCI Configuration",
        response_model=schema.OracleCloudSettings,
    )
    async def oci_profile_update(
        auth_profile: schema.OCIProfileType, payload: schema.OracleCloudSettings
    ) -> schema.OracleCloudSettings:
        """Update OCI Configuration"""
        logger.debug("Received oci_update - auth_profile: %s; payload %s", auth_profile, payload)
        try:
            namespace = server_oci.get_namespace(payload)
        except server_oci.OciException as ex:
            raise HTTPException(status_code=401, detail=str(ex)) from ex

        oci_config = await oci_get(auth_profile)
        try:
            oci_config.namespace = namespace
            oci_config.tenancy = payload.tenancy if payload.tenancy else oci_config.tenancy
            oci_config.region = payload.region if payload.region else oci_config.region
            oci_config.user = payload.user if payload.user else oci_config.user
            oci_config.fingerprint = payload.fingerprint if payload.fingerprint else oci_config.fingerprint
            oci_config.key_file = payload.key_file if payload.key_file else oci_config.key_file
            oci_config.security_token_file = (
                payload.security_token_file if payload.security_token_file else oci_config.security_token_file
            )
        except AttributeError as ex:
            raise HTTPException(status_code=400, detail="OCI: Invalid Payload.") from ex

        # OCI GenAI
        try:
            oci_config.service_endpoint = (
                payload.service_endpoint if payload.service_endpoint else oci_config.service_endpoint
            )
            oci_config.compartment_id = payload.compartment_id if payload.compartment_id else oci_config.compartment_id
            if oci_config.service_endpoint != "" and oci_config.compartment_id != "":
                for model in MODEL_OBJECTS:
                    if "OCI" in model.api:
                        model.enabled = True
                        model.url = oci_config.service_endpoint
        except AttributeError:
            pass
        return oci_config

    @auth.post(
        "/v1/oci/objects/download/{bucket_name}/{auth_profile}",
        description="Download files from Object Storage",
    )
    async def oci_download_objects(
        bucket_name: str,
        auth_profile: schema.OCIProfileType,
        request: list[str],
        client: schema.ClientIdType = Header(...),
    ) -> JSONResponse:
        """Download files from Object Storage"""
        logger.debug(
            "Received oci_download_objects - auth_profile: %s; bucket_name: %s; request: %s",
            auth_profile,
            bucket_name,
            request,
        )
        oci_config = await oci_get(auth_profile)
        # Files should be placed in the embedding folder
        temp_directory = get_temp_directory(client, "embedding")
        for object_name in request:
            server_oci.get_object(temp_directory, object_name, bucket_name, oci_config)

        downloaded_files = [f.name for f in temp_directory.iterdir() if f.is_file()]
        return JSONResponse(status_code=200, content=downloaded_files)

    #################################################
    # prompts Endpoints
    #################################################
    @auth.get(
        "/v1/prompts",
        description="Get all prompt configurations",
        response_model=list[schema.Prompt],
    )
    async def prompts_list(
        category: Optional[schema.PromptCategoryType] = Query(None),
    ) -> list[schema.Prompt]:
        """List all prompts after applying filters if specified"""
        prompts_all = PROMPT_OBJECTS
        # Apply filtering if query parameters are provided
        if category is not None:
            logger.info("Filtering prompts on category: %s", category)
            prompts_all = [prompt for prompt in PROMPT_OBJECTS if prompt.category == category]

        return prompts_all

    @auth.get(
        "/v1/prompts/{category}/{name}",
        description="Get single schema.Prompt Configuration",
        response_model=schema.Prompt,
    )
    async def prompts_get(category: schema.PromptCategoryType, name: schema.PromptNameType) -> schema.Prompt:
        """Get a single schema.Prompt"""
        prompt = next(
            (prompt for prompt in PROMPT_OBJECTS if prompt.category == category and prompt.name == name), None
        )
        if not prompt:
            raise HTTPException(status_code=404, detail=f"Prompt: {name} ({category}) not found.")

        return prompt

    @auth.patch(
        "/v1/prompts/{category}/{name}",
        description="Update Prompt Configuration",
        response_model=schema.Prompt,
    )
    async def prompts_update(
        category: schema.PromptCategoryType, name: schema.PromptNameType, payload: schema.PromptText
    ) -> schema.Prompt:
        """Update a single Prompt"""
        logger.debug("Received %s (%s) Prompt Payload: %s", name, category, payload)
        prompt_upd = await prompts_get(category, name)
        prompt_upd.prompt = payload.prompt

        return await prompts_get(category, name)

    #################################################
    # settings Endpoints
    #################################################
    @auth.get("/v1/settings", description="Get client settings", response_model=schema.Settings)
    async def settings_get(client: schema.ClientIdType) -> schema.Settings:
        """Get settings for a specific client by name"""
        return get_client_settings(client)

    @auth.patch("/v1/settings", description="Update client settings")
    async def settings_update(payload: schema.Settings, client: schema.ClientIdType) -> schema.Settings:
        """Update a single client settings"""
        logger.debug("Received %s Client Payload: %s", client, payload)
        client_settings = get_client_settings(client)

        SETTINGS_OBJECTS.remove(client_settings)
        payload.client = client
        SETTINGS_OBJECTS.append(payload)

        return get_client_settings(client)

    @auth.post("/v1/settings", description="Create new client settings", response_model=schema.Settings)
    async def settings_create(client: schema.ClientIdType) -> schema.Settings:
        """Create a new client, initialise client settings"""
        if any(settings.client == client for settings in SETTINGS_OBJECTS):
            raise HTTPException(status_code=409, detail=f"Client: {client} already exists.")
        default_settings = next((settings for settings in SETTINGS_OBJECTS if settings.client == "default"), None)

        # Copy the default settings
        client_settings = schema.Settings(**default_settings.model_dump())
        client_settings.client = client
        SETTINGS_OBJECTS.append(client_settings)

        return client_settings

    #################################################
    # chat Endpoints
    #################################################
    async def completion_generator(
        client: schema.ClientIdType, request: schema.ChatRequest, call: Literal["completions", "streams"]
    ) -> AsyncGenerator[str, None]:
        """Generate a completion from agent, stream the results"""
        client_settings = get_client_settings(client)
        logger.debug("Settings: %s", client_settings)
        logger.debug("Request: %s", request.model_dump())

        # Establish LL schema.Model Params (if the request specs a model, otherwise override from settings)
        model = request.model_dump()
        if not model["model"]:
            model = client_settings.ll_model.model_dump()

        oci_config = get_client_oci(client)
        # Setup Client schema.Model
        ll_client = await models.get_client(MODEL_OBJECTS, model, oci_config)
        if not ll_client:
            error_response = {
                "id": "error",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "I'm sorry, I'm unable to initialise the Language Model. Please refresh the application.",
                        },
                        "index": 0,
                        "finish_reason": "stop",
                    }
                ],
                "created": int(time.time()),
                "model": model.get("model", "unknown"),
                "object": "chat.completion",
            }
            yield error_response
            return

        # Get Prompts
        try:
            user_sys_prompt = getattr(client_settings.prompts, "sys", "Basic Example")
            sys_prompt = next(
                (prompt for prompt in PROMPT_OBJECTS if prompt.category == "sys" and prompt.name == user_sys_prompt),
                None,
            )
        except AttributeError as ex:
            # schema.Settings not on server-side
            logger.error("A settings exception occurred: %s", ex)
            raise HTTPException(status_code=500, detail="Unexpected Error.") from ex

        # Setup RAG
        embed_client, ctx_prompt, db_conn = None, None, None
        if client_settings.rag.rag_enabled:
            embed_client = await models.get_client(MODEL_OBJECTS, client_settings.rag.model_dump(), oci_config)

            user_ctx_prompt = getattr(client_settings.prompts, "ctx", "Basic Example")
            ctx_prompt = next(
                (prompt for prompt in PROMPT_OBJECTS if prompt.category == "ctx" and prompt.name == user_ctx_prompt),
                None,
            )
            db_conn = get_client_db(client).connection

        kwargs = {
            "input": {"messages": [HumanMessage(content=request.messages[0].content)]},
            "config": RunnableConfig(
                configurable={
                    "thread_id": client,
                    "ll_client": ll_client,
                    "embed_client": embed_client,
                    "db_conn": db_conn,
                },
                metadata={
                    "model_name": model["model"],
                    "use_history": client_settings.ll_model.chat_history,
                    "rag_settings": client_settings.rag,
                    "sys_prompt": sys_prompt,
                    "ctx_prompt": ctx_prompt,
                },
            ),
        }
        logger.debug("Completion Kwargs: %s", kwargs)
        agent: CompiledStateGraph = chatbot.chatbot_graph
        try:
            async for chunk in agent.astream_events(**kwargs, version="v2"):
                # The below will produce A LOT of output; uncomment when desperate
                # logger.debug("Streamed Chunk: %s", chunk)
                if chunk["event"] == "on_chat_model_stream":
                    if "tools_condition" in str(chunk["metadata"]["langgraph_triggers"]):
                        continue  # Skip Tool Call messages
                    if "vs_retrieve" in str(chunk["metadata"]["langgraph_node"]):
                        continue  # Skip Fake-Tool Call messages
                    content = chunk["data"]["chunk"].content
                    if content != "" and call == "streams":
                        yield content.encode("utf-8")
                last_response = chunk["data"]
            if call == "streams":
                yield "[stream_finished]"  # This will break the Chatbot loop
            elif call == "completions":
                final_response = last_response["output"]["final_response"]
                yield final_response  # This will be captured for ChatResponse
        except Exception as ex:
            logger.error("An invoke exception occurred: %s", ex)
            # yield f"I'm sorry; {ex}"
            # TODO(gotsysdba) - If a message is returned;
            # format and return (this should be done in the agent)
            raise HTTPException(status_code=500, detail="Unexpected Error.") from ex

    @auth.post(
        "/v1/chat/completions",
        description="Submit a message for full completion.",
        response_model=schema.ChatResponse,
    )
    async def chat_post(request: schema.ChatRequest, client: schema.ClientIdType = Header(...)) -> schema.ChatResponse:
        """Full Completion Requests"""
        last_message = None
        async for chunk in completion_generator(client, request, "completions"):
            last_message = chunk
        return last_message

    @auth.post(
        "/v1/chat/streams",
        description="Submit a message for streamed completion.",
        response_class=StreamingResponse,
        include_in_schema=False,
    )
    async def chat_stream(request: schema.ChatRequest, client: schema.ClientIdType = Header(...)) -> StreamingResponse:
        """Completion Requests"""
        return StreamingResponse(
            completion_generator(client, request, "streams"),
            media_type="application/octet-stream",
        )

    @auth.get(
        "/v1/chat/history",
        description="Get Chat History",
        response_model=list[schema.ChatMessage],
    )
    async def chat_history(client: schema.ClientIdType = Header(...)) -> list[ChatMessage]:
        """Return Chat History"""
        agent: CompiledStateGraph = chatbot.chatbot_graph
        try:
            state_snapshot = agent.get_state(
                config=RunnableConfig(
                    configurable={
                        "thread_id": client,
                    }
                )
            )
            messages: list[AnyMessage] = state_snapshot.values["messages"]
            chat_messages = convert_to_openai_messages(messages)
            return chat_messages
        except KeyError:
            return [ChatMessage(content="I'm sorry, I have no history of this conversation", role="system")]

    #################################################
    # testbed Endpoints
    #################################################
    @auth.get("/v1/testbed/testsets", description="Get Stored TestSets.", response_model=list[schema.TestSets])
    async def testbed_testsets(client: schema.ClientIdType = Header(...)) -> list[schema.TestSets]:
        """Get a list of stored TestSets, create TestSet objects if they don't exist"""
        testsets = testbed.get_testsets(db_conn=get_client_db(client).connection)
        return testsets

    @auth.get("/v1/testbed/evaluations", description="Get Stored Evaluations.", response_model=list[schema.Evaluation])
    async def testbed_evaluations(
        tid: schema.TestSetsIdType, client: schema.ClientIdType = Header(...)
    ) -> list[schema.Evaluation]:
        """Get Evaluations"""
        evaluations = testbed.get_evaluations(db_conn=get_client_db(client).connection, tid=tid.upper())
        return evaluations

    @auth.get(
        "/v1/testbed/evaluation",
        description="Get Stored Single schema.Evaluation.",
        response_model=schema.EvaluationReport,
    )
    async def testbed_evaluation(
        eid: schema.TestSetsIdType, client: schema.ClientIdType = Header(...)
    ) -> schema.EvaluationReport:
        """Get Evaluations"""
        evaluation = testbed.process_report(db_conn=get_client_db(client).connection, eid=eid.upper())
        return evaluation

    @auth.get("/v1/testbed/testset_qa", description="Get Stored schema.TestSets Q&A.", response_model=schema.TestSetQA)
    async def testbed_testset_qa(
        tid: schema.TestSetsIdType, client: schema.ClientIdType = Header(...)
    ) -> schema.TestSetQA:
        """Get TestSet Q&A"""
        return testbed.get_testset_qa(db_conn=get_client_db(client).connection, tid=tid.upper())

    @auth.delete("/v1/testbed/testset_delete/{tid}", description="Delete a TestSet")
    async def testbed_delete_testset(
        tid: Optional[schema.TestSetsIdType] = None, client: schema.ClientIdType = Header(...)
    ) -> JSONResponse:
        """Delete TestSet"""
        testbed.delete_qa(get_client_db(client).connection, tid.upper())
        return JSONResponse(status_code=200, content={"message": f"TestSet: {tid} deleted."})

    @auth.post("/v1/testbed/testset_load", description="Upsert TestSets.", response_model=schema.TestSetQA)
    async def testbed_upsert_testsets(
        files: list[UploadFile],
        name: schema.TestSetsNameType,
        tid: Optional[schema.TestSetsIdType] = None,
        client: schema.ClientIdType = Header(...),
    ) -> schema.TestSetQA:
        """Update stored TestSet data"""
        created = datetime.now().isoformat()
        db_conn = get_client_db(client).connection
        try:
            for file in files:
                file_content = await file.read()
                content = testbed.jsonl_to_json_content(file_content)
                db_id = testbed.upsert_qa(db_conn, name, created, content, tid)
            db_conn.commit()
        except Exception as ex:
            logger.error("An exception occurred: %s", ex)
            raise HTTPException(status_code=500, detail="Unexpected Error.") from ex

        testset_qa = await testbed_testset_qa(client=client, tid=db_id)
        return testset_qa

    @auth.post("/v1/testbed/testset_generate", description="Generate Q&A Test Set.", response_model=schema.TestSetQA)
    async def testbed_generate_qa(
        files: list[UploadFile],
        name: schema.TestSetsNameType,
        ll_model: schema.ModelNameType = None,
        embed_model: schema.ModelNameType = None,
        questions: int = 2,
        client: schema.ClientIdType = Header(...),
    ) -> schema.TestSetQA:
        """Retrieve contents from a local file uploaded and generate Q&A"""
        # Setup Models
        giskard_ll_model = await models.apply_filter(MODEL_OBJECTS, model_name=ll_model, model_type="ll")
        giskard_embed_model = await models.apply_filter(MODEL_OBJECTS, model_name=embed_model, model_type="embed")
        temp_directory = get_temp_directory(client, "testbed")
        full_testsets = temp_directory / "all_testsets.jsonl"

        for file in files:
            try:
                # Read and save file content
                file_content = await file.read()
                filename = temp_directory / file.filename
                logger.info("Writing Q&A File to: %s", filename)
                with open(filename, "wb") as file:
                    file.write(file_content)

                # Process file for knowledge base
                text_nodes = testbed.load_and_split(filename)
                test_set = testbed.build_knowledge_base(
                    text_nodes, questions, giskard_ll_model[0], giskard_embed_model[0]
                )
                # Save test set
                test_set_filename = temp_directory / f"{name}.jsonl"
                test_set.save(test_set_filename)
                with (
                    open(test_set_filename, "r", encoding="utf-8") as source,
                    open(full_testsets, "a", encoding="utf-8") as destination,
                ):
                    destination.write(source.read())
            except APIConnectionError as ex:
                shutil.rmtree(temp_directory)
                logger.error("APIConnectionError Exception: %s", str(ex))
                raise HTTPException(status_code=424, detail=str(ex)) from ex
            except Exception as ex:
                shutil.rmtree(temp_directory)
                logger.error("Unknown TestSet Exception: %s", str(ex))
                raise HTTPException(status_code=500, detail=f"Unexpected testset error: {str(ex)}.") from ex

            # Store tests in database
            with open(full_testsets, "rb") as file:
                upload_file = UploadFile(file=file, filename=full_testsets)
                testset_qa = await testbed_upsert_testsets(client=client, files=[upload_file], name=name)
            shutil.rmtree(temp_directory)

        return testset_qa

    @auth.post(
        "/v1/testbed/evaluate",
        description="Evaluate Q&A Test Set.",
        response_model=schema.EvaluationReport,
    )
    def testbed_evaluate_qa(
        tid: schema.TestSetsIdType, judge: schema.ModelNameType, client: schema.ClientIdType = Header(...)
    ) -> schema.EvaluationReport:
        """Run evaluate against a testset"""

        def get_answer(question: str):
            """Submit question against the chatbot"""
            request = schema.ChatRequest(
                messages=[ChatMessage(role="human", content=question)],
            )
            ai_response = asyncio.run(chat_post(client=client, request=request))
            return ai_response.choices[0].message.content

        evaluated = datetime.now().isoformat()
        client_settings = get_client_settings(client)
        # Change Disable History
        client_settings.ll_model.chat_history = False
        # Change Grade RAG
        client_settings.rag.grading = False

        db_conn = get_client_db(client).connection
        testset = testbed.get_testset_qa(db_conn=db_conn, tid=tid.upper())
        qa_test = "\n".join(json.dumps(item) for item in testset.qa_data)
        temp_directory = get_temp_directory(client, "testbed")

        with open(temp_directory / f"{tid}_output.txt", "w", encoding="utf-8") as file:
            file.write(qa_test)
        loaded_testset = QATestset.load(temp_directory / f"{tid}_output.txt")

        # Setup Judge Model
        logger.debug("Starting evaluation with Judge: %s", judge)
        oci_config = get_client_oci(client)
        judge_client = asyncio.run(models.get_client(MODEL_OBJECTS, {"model": judge}, oci_config, True))
        report = evaluate(get_answer, testset=loaded_testset, llm_client=judge_client, metrics=[correctness_metric])

        eid = testbed.insert_evaluation(
            db_conn=db_conn,
            tid=tid,
            evaluated=evaluated,
            correctness=report.correctness,
            settings=client_settings.model_dump_json(),
            rag_report=pickle.dumps(report),
        )
        db_conn.commit()
        shutil.rmtree(temp_directory)

        return testbed.process_report(db_conn=db_conn, eid=eid)

    logger.info("Endpoints Loaded.")
