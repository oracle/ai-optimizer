"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore langchain docstore docos vectorstores oraclevs genai hnsw

import copy
import datetime
import json
import math
import os
from pathlib import Path
import shutil
import time
from typing import Union

import bs4

# Langchain
from langchain_community import document_loaders
from langchain_community.document_loaders import WebBaseLoader
from langchain_community.document_loaders.image import UnstructuredImageLoader
from langchain_community.vectorstores import oraclevs as LangchainVS
from langchain_community.vectorstores.oraclevs import OracleVS
from langchain_core.documents import Document as LangchainDocument
from langchain_core.language_models.chat_models import BaseChatModel
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_text_splitters import HTMLHeaderTextSplitter, CharacterTextSplitter

import server.api.utils.databases as utils_databases
import server.api.utils.oci as utils_oci

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
    with open(dst_file_path, "w", encoding="utf-8") as f:
        f.write(json_data)
    file_size = os.path.getsize(dst_file_path)
    logger.info("Wrote split JSON file: %s (%i bytes)", dst_file_path, file_size)

    return dst_file_path


def process_metadata(idx: int, chunk: str, file_metadata: dict = None) -> str:
    """Add Metadata to Split Document"""
    filename = os.path.basename(chunk.metadata["source"])
    file = os.path.splitext(filename)[0]

    split_doc_with_mdata = []
    chunk_metadata = chunk.metadata.copy()
    # Add More Metadata as Required
    chunk_metadata["id"] = f"{file}_{idx}"
    chunk_metadata["filename"] = filename

    # Add file size and timestamp if available
    if file_metadata and filename in file_metadata:
        chunk_metadata["size"] = file_metadata[filename].get("size")
        chunk_metadata["time_modified"] = file_metadata[filename].get("time_modified")
        chunk_metadata["etag"] = file_metadata[filename].get("etag")

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


def _get_document_loader(file: str, extension: str):
    """Get appropriate document loader based on file extension"""
    match extension.lower():
        case "pdf":
            return document_loaders.PyPDFLoader(file), True
        case "html":
            return document_loaders.TextLoader(file), True
        case "md":
            return document_loaders.TextLoader(file), True
        case "csv":
            return document_loaders.CSVLoader(file), True
        case "png" | "jpg" | "jpeg":
            return UnstructuredImageLoader(file), False
        case "txt":
            return document_loaders.TextLoader(file), True
        case _:
            raise ValueError(f"{extension} is not a supported file extension")


def _capture_file_metadata(name: str, stat: os.stat_result, file_metadata: dict) -> None:
    """Capture file metadata if not already provided"""
    if name not in file_metadata:
        file_metadata[name] = {
            "size": stat.st_size,
            "time_modified": datetime.datetime.fromtimestamp(stat.st_mtime, datetime.timezone.utc).isoformat(),
        }


def _process_and_split_document(
    loaded_doc: list,
    split: bool,
    model: str,
    chunk_size: int,
    chunk_overlap: int,
    extension: str,
    file_metadata: dict,
) -> list[LangchainDocument]:
    """Process and split a loaded document"""
    if not split:
        return loaded_doc

    split_doc = split_document(model, chunk_size, chunk_overlap, loaded_doc, extension)
    split_docos = []
    for idx, chunk in enumerate(split_doc, start=1):
        split_doc_with_mdata = process_metadata(idx, chunk, file_metadata)
        split_docos += split_doc_with_mdata
    return split_docos


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
    file_metadata: dict = None,
) -> list[LangchainDocument]:
    """
    Loads file into a Langchain Document.  Calls the Splitter (split_document) function
    Returns the list of the chunks in a LangchainDocument.
    If output_dir, a list of written json files
    """
    split_files = []
    all_split_docos = []

    # If no metadata provided, create from file system
    if file_metadata is None:
        file_metadata = {}

    for file in src_files:
        name = os.path.basename(file)
        stat = os.stat(file)
        extension = os.path.splitext(file)[1][1:]
        logger.info("Loading %s (%i bytes)", name, stat.st_size)

        _capture_file_metadata(name, stat, file_metadata)

        loader, split = _get_document_loader(file, extension)
        loaded_doc = loader.load()
        logger.info("Loaded Pages: %i", len(loaded_doc))

        split_docos = _process_and_split_document(
            loaded_doc, split, model, chunk_size, chunk_overlap, extension, file_metadata
        )

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


def _json_to_doc(file: str) -> list[LangchainDocument]:
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


def _prepare_documents(input_data: Union[list[LangchainDocument], list]) -> list[LangchainDocument]:
    """Convert input data to documents and remove duplicates"""
    # Loop through files and create Documents
    if isinstance(input_data[0], LangchainDocument):
        logger.debug("Processing Documents: %s", input_data)
        documents = input_data
    else:
        documents = []
        for file in input_data:
            logger.info("Processing file: %s into a Document.", file)
            documents.extend(_json_to_doc(file))

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
    return unique_chunks


def _create_temp_vector_store(
    db_conn, vector_store: schema.DatabaseVectorStorage, embed_client: BaseChatModel
) -> tuple[OracleVS, schema.DatabaseVectorStorage]:
    """Create temporary vector store for staging"""
    vector_store_tmp = copy.copy(vector_store)
    vector_store_tmp.vector_store = f"{vector_store.vector_store}_TMP"

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
    return vs_tmp, vector_store_tmp


def _embed_documents_in_batches(vs_tmp: OracleVS, unique_chunks: list[LangchainDocument], rate_limit: int) -> None:
    """Embed documents in batches with rate limiting"""
    batch_size = 500
    logger.info("Embedding chunks in batches of: %i", batch_size)

    for i in range(0, len(unique_chunks), batch_size):
        batch = unique_chunks[i : i + batch_size]
        current_count = min(len(unique_chunks), i + batch_size)
        logger.info("Processing: %i Chunks of %i (Rate Limit: %i)", current_count, len(unique_chunks), rate_limit)

        OracleVS.add_documents(vs_tmp, documents=batch)

        if rate_limit > 0:
            interval = 60 / rate_limit
            logger.info("Rate Limiting: sleeping for %i seconds", interval)
            time.sleep(interval)


def _merge_and_index_vector_store(
    db_conn, vector_store: schema.DatabaseVectorStorage, vector_store_tmp: schema.DatabaseVectorStorage, embed_client
) -> None:
    """Merge temporary vector store into real one and create index"""
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
        params = {"idx_name": vector_store_idx, "idx_type": vector_store.index_type}
        LangchainVS.create_index(db_conn, vs_real, params)
    except Exception as ex:
        logger.error("Unable to create vector index: %s", ex)


##########################################
# Vector Store
##########################################
def update_vs_comment(vector_store: schema.DatabaseVectorStorage, db_details: schema.Database) -> None:
    """Comment on Existing Vector Store"""
    db_conn = utils_databases.connect(db_details)

    _, store_comment = functions.get_vs_table(**vector_store.model_dump(exclude={"database", "vector_store"}))
    comment = f"COMMENT ON TABLE {vector_store.vector_store} IS 'GENAI: {store_comment}'"
    utils_databases.execute_sql(db_conn, comment)
    utils_databases.disconnect(db_conn)


def populate_vs(
    vector_store: schema.DatabaseVectorStorage,
    db_details: schema.Database,
    embed_client: BaseChatModel,
    input_data: Union[list["LangchainDocument"], list] = None,
    rate_limit: int = 0,
) -> None:
    """Populate the Vector Storage"""
    unique_chunks = _prepare_documents(input_data)

    # Establish a dedicated connection to the database
    db_conn = utils_databases.connect(db_details)

    # Create temporary vector store and embed documents
    vs_tmp, vector_store_tmp = _create_temp_vector_store(db_conn, vector_store, embed_client)
    _embed_documents_in_batches(vs_tmp, unique_chunks, rate_limit)

    # Merge and index
    _merge_and_index_vector_store(db_conn, vector_store, vector_store_tmp, embed_client)

    # Comment the VS table
    update_vs_comment(vector_store, db_details)


##########################################
# Vector Store Refresh
##########################################
def get_vector_store_by_alias(db_details: schema.Database, alias: str) -> schema.DatabaseVectorStorage:
    """Retrieve vector store configuration by alias"""
    db_conn = utils_databases.connect(db_details)

    try:
        # Query for vector store with the given alias - using all_tab_comments like _get_vs does
        query = """
            SELECT ut.table_name,
                   REPLACE(utc.comments, 'GENAI: ', '') AS comments
            FROM all_tab_comments utc, all_tables ut
            WHERE utc.table_name = ut.table_name
            AND utc.comments LIKE 'GENAI:%'
        """

        cursor = db_conn.cursor()
        cursor.execute(query)
        results = cursor.fetchall()

        # Find the vector store with matching alias
        for table_name, comments in results:
            try:
                comments_dict = json.loads(comments)
                if comments_dict.get("alias") == alias:
                    vs_config = schema.DatabaseVectorStorage(vector_store=table_name, **comments_dict)
                    return vs_config
            except (json.JSONDecodeError, KeyError):
                logger.warning("Failed to parse comments for table %s", table_name)
                continue

        raise ValueError(f"Vector store with alias '{alias}' not found")

    finally:
        utils_databases.disconnect(db_conn)


def get_total_chunks_count(db_details: schema.Database, vector_store_name: str) -> int:
    """Get total number of chunks in the vector store"""
    db_conn = utils_databases.connect(db_details)

    try:
        query = f'SELECT COUNT(*) FROM "{vector_store_name}"'
        cursor = db_conn.cursor()
        cursor.execute(query)
        result = cursor.fetchone()
        return result[0] if result else 0
    except Exception as ex:
        logger.warning("Could not count chunks in %s: %s", vector_store_name, ex)
        return 0
    finally:
        utils_databases.disconnect(db_conn)


def get_processed_objects_metadata(db_details: schema.Database, vector_store_name: str) -> dict:
    """Get metadata of previously processed objects for a vector store"""
    db_conn = utils_databases.connect(db_details)

    try:
        # Retrieve all metadata and parse in Python since JSON_VALUE doesn't work
        logger.info("Retrieving metadata from %s", vector_store_name)
        cursor = db_conn.cursor()

        # Get all unique metadata entries - metadata is automatically converted to dict by Oracle driver
        query = f'SELECT DISTINCT metadata FROM "{vector_store_name}"'
        logger.info("SQL Query: %s", query)
        cursor.execute(query)
        results = cursor.fetchall()
        logger.info("Query returned %s metadata entries", len(results))

        # Parse metadata in Python to extract filename, etag, etc.
        processed_objects = {}
        for row in results:
            metadata = row[0]
            # metadata is already a dict thanks to Oracle driver
            if isinstance(metadata, dict) and "filename" in metadata:
                filename = metadata.get("filename")
                if filename:
                    processed_objects[filename] = {
                        "etag": metadata.get("etag"),
                        "time_modified": metadata.get("time_modified"),
                        "size": metadata.get("size"),
                    }

        if processed_objects:
            logger.info(
                "Found %i previously processed objects (new format) in %s", len(processed_objects), vector_store_name
            )
            return processed_objects

        # Try old format - check for 'source' field in metadata
        logger.info("No filename field found, trying old format with 'source' field")
        for row in results:
            metadata = row[0]
            if isinstance(metadata, dict) and "source" in metadata:
                source_path = metadata.get("source")
                if source_path:
                    filename = os.path.basename(source_path)
                    # For old format, we don't have etag/time_modified, so just mark as existing
                    processed_objects[filename] = {"etag": None, "time_modified": None, "size": None}

        if processed_objects:
            logger.info(
                "Found %s previously processed objects (old format) in %s",
                len(processed_objects),
                vector_store_name,
            )
            logger.info(
                "Note: Old metadata format detected. Files will be re-processed with new metadata on next refresh."
            )
            return processed_objects

        logger.info("No previously processed objects found in %s", vector_store_name)
        return {}

    except Exception as ex:
        # If table doesn't have metadata column or query fails, return empty dict
        logger.warning("Could not retrieve processed objects metadata from %s: %s", vector_store_name, ex)
        return {}
    finally:
        utils_databases.disconnect(db_conn)


def get_vector_store_files(db_details: schema.Database, vector_store_name: str) -> dict:
    """Get list of files embedded in a vector store with statistics"""
    db_conn = utils_databases.connect(db_details)

    try:
        logger.info("Retrieving file list from %s", vector_store_name)
        cursor = db_conn.cursor()

        # Get all metadata entries with chunk count
        query = f'SELECT metadata FROM "{vector_store_name}"'
        logger.info("SQL Query: %s", query)
        cursor.execute(query)
        results = cursor.fetchall()
        logger.info("Query returned %s chunks", len(results))

        # Parse metadata to extract file information
        files_info = {}
        total_identified_chunks = 0
        orphaned_chunks = 0

        for row in results:
            metadata = row[0]

            # Skip non-dict metadata
            if not isinstance(metadata, dict):
                orphaned_chunks += 1
                continue

            # Try new format first (filename field)
            filename = metadata.get("filename")
            if not filename and "source" in metadata:
                # Fall back to old format
                filename = os.path.basename(metadata.get("source", ""))

            # Skip chunks without filename
            if not filename:
                orphaned_chunks += 1
                continue

            # Initialize file entry if needed
            if filename not in files_info:
                # Convert size to int if it's a Decimal (from Oracle NUMBER type)
                size_value = metadata.get("size")
                if size_value is not None:
                    size_value = int(size_value)

                files_info[filename] = {
                    "filename": filename,
                    "chunk_count": 0,
                    "etag": metadata.get("etag"),
                    "time_modified": metadata.get("time_modified"),
                    "size": size_value,
                }

            files_info[filename]["chunk_count"] += 1
            total_identified_chunks += 1

        # Convert to list and sort by filename
        file_list = sorted(files_info.values(), key=lambda x: x["filename"])

        result = {
            "vector_store": vector_store_name,
            "total_files": len(file_list),
            "total_chunks": total_identified_chunks,
            "orphaned_chunks": orphaned_chunks,
            "files": file_list,
        }

        if orphaned_chunks > 0:
            logger.warning(
                "Found %s orphaned chunks without valid filename metadata in %s",
                orphaned_chunks,
                vector_store_name,
            )

        logger.info("Found %s files with %s total chunks in %s", len(file_list), len(results), vector_store_name)
        return result

    except Exception as ex:
        logger.error("Could not retrieve file list from %s: %s", vector_store_name, ex)
        raise
    finally:
        utils_databases.disconnect(db_conn)


def refresh_vector_store_from_bucket(
    vector_store_config: schema.DatabaseVectorStorage,
    bucket_name: str,
    bucket_objects: list[dict],
    db_details: schema.Database,
    embed_client,
    oci_config,
    rate_limit: int = 0,
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
            "message": "No new or modified files to process",
        }

    temp_directory = get_temp_directory("refresh", "embedding")
    logger.info("Processing %d objects for vector store refresh", len(bucket_objects))

    try:
        # Download changed objects
        downloaded_files = []
        for obj in bucket_objects:
            try:
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
                "errors": ["Failed to download any objects from bucket"],
            }

        # Build file metadata dict from bucket objects
        file_metadata = {}
        for obj in bucket_objects:
            filename = os.path.basename(obj["name"])
            size_value = obj.get("size")
            if size_value is not None:
                size_value = int(size_value)
            file_metadata[filename] = {
                "size": size_value,
                "time_modified": obj.get("time_modified"),
                "etag": obj.get("etag"),
                "bucket_name": bucket_name,
            }
        logger.info("Built metadata dict for %d files from bucket objects", len(file_metadata))

        # Process documents with metadata
        split_docos, _ = load_and_split_documents(
            downloaded_files,
            vector_store_config.model,
            vector_store_config.chunk_size,
            vector_store_config.chunk_overlap,
            write_json=False,
            output_dir=None,
            file_metadata=file_metadata,
        )

        # Metadata already set by load_and_split_documents with file_metadata parameter
        logger.info("Processed %s document chunks with OCI bucket metadata", len(split_docos))

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
            "new_files": len(bucket_objects),
            "updated_files": 0,  # All are treated as new for now
            "total_chunks": len(split_docos),
            "message": f"Successfully processed {len(downloaded_files)} files and {len(split_docos)} chunks",
        }

    finally:
        # Clean up temporary directory
        if temp_directory.exists():
            shutil.rmtree(temp_directory)
