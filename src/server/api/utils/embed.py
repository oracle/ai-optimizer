"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore langchain, docstore, docos, vectorstores, oraclevs, genai, hnsw

import json
import copy
import math
import os
from pathlib import Path
import time
from typing import Union

import bs4

# Langchain
from langchain_community import document_loaders
from langchain_community.document_loaders import WebBaseLoader
from langchain_community.document_loaders.image import UnstructuredImageLoader
from langchain_community.vectorstores import oraclevs as LangchainVS
from langchain_community.vectorstores.oraclevs import OracleVS
from langchain_core.language_models.chat_models import BaseChatModel
from langchain.docstore.document import Document as LangchainDocument
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_text_splitters import HTMLHeaderTextSplitter, CharacterTextSplitter

import server.api.utils.databases as utils_databases

from common import schema, functions

from common import logging_config

logger = logging_config.logging.getLogger("api.utils.embed")


def get_temp_directory(client: schema.ClientIdType, function: str) -> Path:
    """Return the path to store temporary files"""
    if Path("/app/tmp").exists() and Path("/app/tmp").is_dir():
        client_folder = Path("/app/tmp") / client / function
    else:
        client_folder = Path("/tmp") / client / function
    client_folder.mkdir(parents=True, exist_ok=True)
    logger.debug("Created temporary directory: %s", client_folder)
    return client_folder


def doc_to_json(document: LangchainDocument, file: str, output_dir: str = None) -> list:
    """Creates a JSON file of the Document.  Returns the json file destination"""
    src_file_name = os.path.basename(file)
    dst_file_name = "_" + os.path.splitext(src_file_name)[0] + ".json"

    docs_dict = [doc.to_json() for doc in document]
    json_data = json.dumps(docs_dict, indent=4)

    dst_file_path = os.path.join(output_dir, dst_file_name)
    with open(dst_file_path, "w", encoding="utf-8") as file:
        file.write(json_data)
    file_size = os.path.getsize(dst_file_path)
    logger.info("Wrote split JSON file: %s (%i bytes)", dst_file_path, file_size)

    return dst_file_path


def process_metadata(idx: int, chunk: str) -> str:
    """Add Metadata to Split Document"""
    filename = os.path.basename(chunk.metadata["source"])
    file = os.path.splitext(filename)[0]

    split_doc_with_mdata = []
    chunk_metadata = chunk.metadata.copy()
    # Add More Metadata as Required
    chunk_metadata["id"] = f"{file}_{idx}"
    chunk_metadata["filename"] = filename
    split_doc_with_mdata.append(LangchainDocument(page_content=str(chunk.page_content), metadata=chunk_metadata))
    return split_doc_with_mdata


def split_document(
    model: str,
    chunk_size: int,
    chunk_overlap: int,
    document: list[LangchainDocument],
    extension: str,
) -> list[LangchainDocument]:
    """
    Split documents into chunks of size `chunk_size` characters and return a list of documents.
    """
    ##################################
    # Splitters - Start
    ##################################
    logger.info("Splitting for %s", model)
    chunk_overlap_ceil = math.ceil(chunk_overlap)
    match model:
        case "text-embedding*":
            text_splitter = CharacterTextSplitter.from_tiktoken_encoder(
                separator="\n\n",
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap_ceil,
                is_separator_regex=False,
                model_id=model,
                encoding_name=model,
            )
        case _:
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap_ceil,
                add_start_index=True,
                strip_whitespace=True,
                length_function=len,
            )
    ## HTML
    headers_to_split_on = [
        ("h1", "Header 1"),
        ("h2", "Header 2"),
        ("h3", "Header 3"),
        ("h4", "Header 4"),
        ("h5", "Header 5"),
    ]
    html_splitter = HTMLHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
    ##################################
    # Splitters - End
    ##################################
    match extension.lower():
        case "pdf":
            doc_split = text_splitter.split_documents(document)
        case "html":
            tmp_meta = document[0].metadata
            doc_split = html_splitter.split_text(document[0].page_content)
            # Update metadata with source
            for doc in doc_split:
                doc.metadata.update(tmp_meta)
        case "pdf" | "md" | "txt" | "csv":
            doc_split = text_splitter.split_documents(document)
        case _:
            raise ValueError(f"Unsupported file type: {extension.lower()}")

    logger.info("Number of Chunks: %i", len(doc_split))
    return doc_split


##########################################
# Documents
##########################################
def load_and_split_documents(
    src_files: list,
    model: str,
    chunk_size: int,
    chunk_overlap: int,
    write_json: bool = False,
    output_dir: str = None,
) -> list[LangchainDocument]:
    """
    Loads file into a Langchain Document.  Calls the Splitter (split_document) function
    Returns the list of the chunks in a LangchainDocument.
    If output_dir, a list of written json files
    """
    split_files = []
    all_split_docos = []
    for file in src_files:
        name = os.path.basename(file)
        stat = os.stat(file)
        extension = os.path.splitext(file)[1][1:]
        logger.info("Loading %s (%i bytes)", name, stat.st_size)
        split = True
        match extension.lower():
            case "pdf":
                loader = document_loaders.PyPDFLoader(file)
            case "html":
                # Use TextLoader to preserve for header split
                loader = document_loaders.TextLoader(file)
            case "md":
                loader = document_loaders.TextLoader(file)
            case "csv":
                loader = document_loaders.CSVLoader(file)
            case "png" | "jpg" | "jpeg":
                loader = UnstructuredImageLoader(file)
                split = False
            case _:
                raise ValueError(f"{extension} is not a supported file extension")

        loaded_doc = loader.load()
        logger.info("Loaded Pages: %i", len(loaded_doc))

        # Chunk the File
        if split:
            split_doc = split_document(model, chunk_size, chunk_overlap, loaded_doc, extension)
            # Add IDs to metadata
            split_docos = []
            for idx, chunk in enumerate(split_doc, start=1):
                split_doc_with_mdata = process_metadata(idx, chunk)
                split_docos += split_doc_with_mdata
        else:
            split_files = file
            all_split_docos = loaded_doc

        if write_json and output_dir:
            split_files.append(doc_to_json(split_docos, file, output_dir))
        all_split_docos += split_docos
    logger.info("Total Number of Chunks: %i", len(all_split_docos))

    return all_split_docos, split_files


##########################################
# Web
##########################################
def load_and_split_url(
    model: str,
    url: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[LangchainDocument]:
    """
    Loads URL into a Langchain Document.  Calls the Splitter (split_document) function
    Returns the list of the chunks in a LangchainDocument.
    If output_dir, a list of written json files
    """
    split_docos = []
    split_files = []

    logger.info("Loading %s", url)
    loader = WebBaseLoader(
        web_paths=(f"{url}",),
        bs_kwargs={"parse_only": bs4.SoupStrainer()},
    )

    loaded_doc = loader.load()
    logger.info("Document Size: %s bytes", str(loaded_doc.__sizeof__()))
    logger.info("Loaded Pages: %i", len(loaded_doc))

    # Chunk the File
    split_doc = split_document(model, chunk_size, chunk_overlap, loaded_doc, "html")

    # Add IDs to metadata
    for idx, chunk in enumerate(split_doc, start=1):
        split_doc_with_mdata = process_metadata(idx, chunk)
        split_docos += split_doc_with_mdata

    logger.info("Total Number of Chunks: %i", len(split_docos))
    if len(split_docos) == 0:
        raise ValueError("Input source contains no chunk-able data.")

    return split_docos, split_files


##########################################
# Vector Store
##########################################
def populate_vs(
    vector_store: schema.DatabaseVectorStorage,
    db_details: schema.Database,
    embed_client: BaseChatModel,
    input_data: Union[list["LangchainDocument"], list] = None,
    rate_limit: int = 0,
) -> None:
    """Populate the Vector Storage"""
    # Copy our vector storage object so can process a tmp one
    vector_store_tmp = copy.copy(vector_store)
    vector_store_tmp.vector_store = f"{vector_store.vector_store}_TMP"

    def json_to_doc(file: str):
        """Creates a list of LangchainDocument from a JSON file. Returns the list of documents."""
        logger.info("Converting %s to Document", file)

        with open(file, "r", encoding="utf-8") as document:
            chunks = json.load(document)
            docs = []
            for chunk in chunks:
                page_content = chunk["kwargs"]["page_content"]
                metadata = chunk["kwargs"]["metadata"]
                docs.append(LangchainDocument(page_content=str(page_content), metadata=metadata))

        logger.info("Total Chunk Size: %i bytes", docs.__sizeof__())
        logger.info("Chunks ingested: %i", len(docs))
        return docs

    # Loop through files and create Documents
    if isinstance(input_data[0], LangchainDocument):
        logger.debug("Processing Documents: %s", input_data)
        documents = input_data
    else:
        documents = []
        for file in input_data:
            logger.info("Processing file: %s into a Document.", file)
            documents.extend(json_to_doc(file))

    logger.info("Size of Payload: %i bytes", documents.__sizeof__())
    logger.info("Total Chunks: %i", len(documents))

    # Remove duplicates (copy-writes, etc)
    unique_texts = {}
    unique_chunks = []
    for chunk in documents:
        if chunk.page_content not in unique_texts:
            unique_texts[chunk.page_content] = True
            unique_chunks.append(chunk)
    logger.info("Total Unique Chunks: %i", len(unique_chunks))

    # Creates a TEMP Vector Store Table; which may already exist
    # Establish a dedicated connection to the database
    db_conn = utils_databases.connect(db_details)
    # This is to allow re-using an existing VS; will merge this over later
    utils_databases.drop_vs(db_conn, vector_store_tmp.vector_store)
    logger.info("Establishing initial vector store")
    logger.debug("Embed Client: %s", embed_client)
    vs_tmp = OracleVS(
        client=db_conn,
        embedding_function=embed_client,
        table_name=vector_store_tmp.vector_store,
        distance_strategy=vector_store.distance_metric,
        query="AI Optimizer for Apps - Powered by Oracle",
    )

    # Batch Size does not have a measurable impact on performance
    # but does eliminate issues with timeouts
    # Careful increasing as may break token rate limits

    batch_size = 500
    logger.info("Embedding chunks in batches of: %i", batch_size)
    for i in range(0, len(unique_chunks), batch_size):
        batch = unique_chunks[i : i + batch_size]
        logger.info(
            "Processing: %i Chunks of %i (Rate Limit: %i)",
            len(unique_chunks) if len(unique_chunks) < i + batch_size else i + batch_size,
            len(unique_chunks),
            rate_limit,
        )
        OracleVS.add_documents(vs_tmp, documents=batch)
        if rate_limit > 0:
            interval = 60 / rate_limit
            logger.info("Rate Limiting: sleeping for %i seconds", interval)
            time.sleep(interval)

    # Create our real vector storage if doesn't exist
    vs_real = OracleVS(
        client=db_conn,
        embedding_function=embed_client,
        table_name=vector_store.vector_store,
        distance_strategy=vector_store.distance_metric,
        query="AI Optimizer for Apps - Powered by Oracle",
    )
    vector_store_idx = f"{vector_store.vector_store}_IDX"
    if vector_store.index_type == "HNSW":
        LangchainVS.drop_index_if_exists(db_conn, vector_store_idx)

    # Perform the Merge
    merge_sql = f"""
        INSERT INTO {vector_store.vector_store} SELECT * FROM {vector_store_tmp.vector_store} src
         WHERE NOT EXISTS (SELECT 1 FROM {vector_store.vector_store} tgt WHERE tgt.ID = src.ID)
    """
    logger.info("Merging %s into %s", vector_store_tmp.vector_store, vector_store.vector_store)
    utils_databases.execute_sql(db_conn, merge_sql)
    utils_databases.drop_vs(db_conn, vector_store_tmp.vector_store)

    # Build the Index
    logger.info("Creating index on: %s", vector_store.vector_store)
    try:
        index_type = vector_store.index_type
        params = {"idx_name": vector_store_idx, "idx_type": index_type}
        LangchainVS.create_index(db_conn, vs_real, params)
    except Exception as ex:
        logger.error("Unable to create vector index: %s", ex)

    # Comment the VS table
    _, store_comment = functions.get_vs_table(**vector_store.model_dump(exclude={"database", "vector_store"}))
    comment = f"COMMENT ON TABLE {vector_store.vector_store} IS 'GENAI: {store_comment}'"
    utils_databases.execute_sql(db_conn, comment)
    utils_databases.disconnect(db_conn)


##########################################
# Vector Store Refresh
##########################################
def get_vector_store_by_alias(db_details: schema.Database, alias: str) -> schema.DatabaseVectorStorage:
    """Retrieve vector store configuration by alias"""
    db_conn = utils_databases.connect(db_details)

    try:
        # Query for vector store with the given alias
        query = """
            SELECT table_name, table_comment
            FROM user_tables
            WHERE table_name LIKE 'VS_%'
            AND table_comment LIKE '%GENAI:%'
            AND REGEXP_SUBSTR(table_comment, 'alias:"([^"]+)"', 1, 1, NULL, 1) = :alias
        """

        cursor = db_conn.cursor()
        cursor.execute(query, {"alias": alias})
        result = cursor.fetchone()

        if not result:
            raise ValueError(f"Vector store with alias '{alias}' not found")

        table_name, comment = result

        # Parse the comment to extract parameters
        import re

        # Extract parameters from comment using regex
        model_match = re.search(r'model:"([^"]+)"', comment)
        chunk_size_match = re.search(r'chunk_size:(\d+)', comment)
        chunk_overlap_match = re.search(r'chunk_overlap:(\d+)', comment)
        distance_metric_match = re.search(r'distance_metric:"([^"]+)"', comment)
        index_type_match = re.search(r'index_type:"([^"]+)"', comment)

        if not all([model_match, chunk_size_match, chunk_overlap_match, distance_metric_match, index_type_match]):
            raise ValueError(f"Could not parse vector store parameters from comment")

        vs_config = schema.DatabaseVectorStorage(
            vector_store=table_name,
            alias=alias,
            model=model_match.group(1),
            chunk_size=int(chunk_size_match.group(1)),
            chunk_overlap=int(chunk_overlap_match.group(1)),
            distance_metric=distance_metric_match.group(1),
            index_type=index_type_match.group(1)
        )

        return vs_config

    finally:
        utils_databases.disconnect(db_conn)


def get_processed_objects_metadata(db_details: schema.Database, vector_store_name: str) -> dict:
    """Get metadata of previously processed objects for a vector store"""
    db_conn = utils_databases.connect(db_details)

    try:
        # Query metadata from the vector store table
        query = f"""
            SELECT DISTINCT
                JSON_VALUE(metadata, '$.filename') as filename,
                JSON_VALUE(metadata, '$.etag') as etag,
                JSON_VALUE(metadata, '$.time_modified') as time_modified,
                JSON_VALUE(metadata, '$.size') as size
            FROM {vector_store_name}
            WHERE JSON_VALUE(metadata, '$.filename') IS NOT NULL
        """

        cursor = db_conn.cursor()
        cursor.execute(query)
        results = cursor.fetchall()

        processed_objects = {}
        for row in results:
            filename, etag, time_modified, size = row
            processed_objects[filename] = {
                "etag": etag,
                "time_modified": time_modified,
                "size": int(size) if size else None
            }

        return processed_objects

    finally:
        utils_databases.disconnect(db_conn)


def refresh_vector_store_from_bucket(
    vector_store_config: schema.DatabaseVectorStorage,
    bucket_name: str,
    bucket_objects: list[dict],
    db_details: schema.Database,
    embed_client,
    oci_config,
    rate_limit: int = 0
) -> dict:
    """
    Refresh vector store with new/modified objects from OCI bucket

    Args:
        vector_store_config: Existing vector store configuration
        bucket_name: OCI bucket name
        bucket_objects: List of new/modified objects to process
        db_details: Database configuration
        embed_client: Embedding client
        oci_config: OCI configuration
        rate_limit: Rate limit in requests per minute

    Returns:
        Dict with processing results
    """
    if not bucket_objects:
        return {
            "processed_files": 0,
            "new_files": 0,
            "updated_files": 0,
            "total_chunks": 0,
            "message": "No new or modified files to process"
        }

    temp_directory = get_temp_directory("refresh", "embedding")
    logger.info("Processing %d objects for vector store refresh", len(bucket_objects))

    try:
        # Download changed objects
        downloaded_files = []
        for obj in bucket_objects:
            try:
                import server.api.utils.oci as utils_oci
                file_path = utils_oci.get_object(str(temp_directory), obj["name"], bucket_name, oci_config)
                downloaded_files.append(file_path)
            except Exception as ex:
                logger.error("Failed to download object %s: %s", obj["name"], ex)
                continue

        if not downloaded_files:
            return {
                "processed_files": 0,
                "new_files": 0,
                "updated_files": 0,
                "total_chunks": 0,
                "message": "No files could be downloaded",
                "errors": ["Failed to download any objects from bucket"]
            }

        # Process documents
        split_docos, _ = load_and_split_documents(
            downloaded_files,
            vector_store_config.model,
            vector_store_config.chunk_size,
            vector_store_config.chunk_overlap,
            write_json=False,
            output_dir=None,
        )

        # Update metadata with bucket information
        for doc in split_docos:
            if "source" in doc.metadata:
                filename = os.path.basename(doc.metadata["source"])
                # Find the corresponding bucket object
                bucket_obj = next((obj for obj in bucket_objects if obj["name"] == filename), None)
                if bucket_obj:
                    doc.metadata.update({
                        "etag": bucket_obj["etag"],
                        "time_modified": bucket_obj["time_modified"],
                        "size": bucket_obj["size"],
                        "bucket_name": bucket_name
                    })

        # Populate vector store
        populate_vs(
            vector_store=vector_store_config,
            db_details=db_details,
            embed_client=embed_client,
            input_data=split_docos,
            rate_limit=rate_limit,
        )

        return {
            "processed_files": len(downloaded_files),
            "new_files": len([obj for obj in bucket_objects]),
            "updated_files": 0,  # All are treated as new for now
            "total_chunks": len(split_docos),
            "message": f"Successfully processed {len(downloaded_files)} files and {len(split_docos)} chunks"
        }

    finally:
        # Clean up temporary directory
        import shutil
        if temp_directory.exists():
            shutil.rmtree(temp_directory)
