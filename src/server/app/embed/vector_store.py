"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Vector store operations — populate, merge, index, query, and metadata management.

Sync LangChain OracleVS operations are bridged to async via ``asyncio.to_thread()``.
"""
# spell-checker:ignore hnsw oraclevs vectorstores docos docling

import asyncio
import copy
import json
import logging
import math
import os
import re
import time
from typing import Optional, Union, cast

import oracledb
from langchain_core.documents import Document
from langchain_core.embeddings.embeddings import Embeddings
from langchain_oracledb.vectorstores.oraclevs import (
    DistanceStrategy,
    OracleVS,
    create_index,
    drop_index_if_exists,
)

from server.app.database.config import create_sync_connection
from server.app.database.registry import discover_vector_stores
from server.app.database.schemas import DatabaseConfig
from server.app.database.sql import ResultSetTooLargeError, execute_sql, validate_vs_table_name
from server.app.embed.document import json_to_doc
from server.app.embed.schemas import DoclingDocumentChunk, VectorStoreConfig
from server.app.models.schemas import ModelIdentity

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# VS table name / comment generation
# ---------------------------------------------------------------------------


def generate_vs_metadata(
    embedding_model: ModelIdentity,
    chunk_size: int,
    chunk_overlap: int,
    distance_strategy: Union[DistanceStrategy, str],
    index_type: str = "HNSW",
    alias: Optional[str] = None,
    description: Optional[str] = None,
) -> tuple[str, str]:
    """Generate a vector store table name and JSON comment string.

    The comment JSON uses the new field names (``embedding_model``,
    ``distance_strategy``) so that ``discover_vector_stores()`` can parse
    it without legacy field mapping.

    Returns:
        ``(table_name, comment_json)``
    """
    chunk_overlap_ceil = math.ceil(chunk_overlap)
    model_str = f"{embedding_model.provider}_{embedding_model.id}"
    strategy_str = (
        distance_strategy.value if isinstance(distance_strategy, DistanceStrategy) else str(distance_strategy)
    )

    table_string = f"{model_str}_{chunk_size}_{chunk_overlap_ceil}_{strategy_str}_{index_type}"
    if alias:
        table_string = f"{alias}_{table_string}"
    table_name = re.sub(r"\W", "_", table_string.upper())

    comment_dict = {
        "alias": alias,
        "description": description,
        "model": f"{embedding_model.provider}/{embedding_model.id}",
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap_ceil,
        "distance_strategy": strategy_str,
        "index_type": index_type,
    }
    comment_json = json.dumps(comment_dict)

    LOGGER.debug("Vector Store Table: %s; Comment: %s", table_name, comment_json)
    return table_name, comment_json


# ---------------------------------------------------------------------------
# Sync vector store operations (run inside asyncio.to_thread)
# ---------------------------------------------------------------------------


def _prepare_documents(input_data: Union[list[DoclingDocumentChunk], list[str]]) -> list[DoclingDocumentChunk]:
    """Convert input data to documents and remove duplicates."""
    if not input_data:
        LOGGER.info("No documents to prepare")
        return []

    if isinstance(input_data[0], DoclingDocumentChunk):
        documents: list[DoclingDocumentChunk] = cast(list[DoclingDocumentChunk], input_data)
    else:
        documents = []
        for file_path in input_data:
            LOGGER.info("Processing file: %s into a Document.", file_path)
            documents.extend(json_to_doc(str(file_path)))

    LOGGER.info("Total Chunks: %i", len(documents))

    unique_texts: dict = {}
    unique_chunks: list[DoclingDocumentChunk] = []
    for chunk in documents:
        if chunk.page_content not in unique_texts:
            unique_texts[chunk.page_content] = True
            unique_chunks.append(chunk)
    LOGGER.info("Total Unique Chunks: %i", len(unique_chunks))
    return unique_chunks


def _create_temp_vector_store(
    db_conn: oracledb.Connection,
    vector_store: VectorStoreConfig,
    embed_client: Embeddings,
) -> tuple[OracleVS, VectorStoreConfig]:
    """Create a temporary vector store for staging."""
    if vector_store.vector_store is None:
        raise ValueError("vector_store.vector_store must be set")
    safe_name = validate_vs_table_name(vector_store.vector_store)
    vector_store_tmp = copy.copy(vector_store)
    safe_tmp_name = f"{safe_name}_TMP"
    vector_store_tmp.vector_store = safe_tmp_name

    # Drop temp table if exists
    try:
        with db_conn.cursor() as cur:
            cur.execute(f'DROP TABLE "{safe_tmp_name}" PURGE')
    except oracledb.DatabaseError as exc:
        if exc.args and getattr(exc.args[0], "code", None) == 942:
            pass  # Table doesn't exist — fine
        else:
            raise

    LOGGER.info("Establishing temporary vector store: %s", safe_tmp_name)
    strategy = vector_store.distance_strategy or DistanceStrategy.COSINE

    vs_tmp = OracleVS(
        client=db_conn,
        embedding_function=embed_client,
        table_name=safe_tmp_name,
        distance_strategy=strategy,
        query="AI Optimizer for Apps - Powered by Oracle",
    )
    return vs_tmp, vector_store_tmp


def _embed_documents_in_batches(
    vs_tmp: OracleVS,
    unique_chunks: list[DoclingDocumentChunk],
    rate_limit: int,
) -> None:
    """Embed documents in batches with optional rate limiting."""
    batch_size = 500
    LOGGER.info("Embedding chunks in batches of: %i", batch_size)

    for i in range(0, len(unique_chunks), batch_size):
        batch = unique_chunks[i : i + batch_size]
        current_count = min(len(unique_chunks), i + batch_size)
        LOGGER.info("Processing: %i Chunks of %i (Rate Limit: %i)", current_count, len(unique_chunks), rate_limit)

        ids = [
            str(
                getattr(doc, "id", None)
                or (doc.metadata.get("id") if isinstance(doc.metadata, dict) else None)
                or f"CHUNK_{i + j + 1}"
            )
            for j, doc in enumerate(batch)
        ]

        OracleVS.add_documents(vs_tmp, documents=cast(list[Document], batch), ids=ids)

        if rate_limit > 0:
            interval = 60 / rate_limit
            LOGGER.info("Rate Limiting: sleeping for %i seconds", interval)
            time.sleep(interval)


def _normalize_metadata_oson(db_conn: oracledb.Connection, table_name: str) -> None:
    """Re-encode the ``metadata`` JSON column server-side so ORDS can render it.

    ``langchain_oracledb.add_texts`` binds metadata via ``DB_TYPE_JSON``
    so python-oracledb encodes the OSON client-side; that dialect
    isn't what ORDS / Database Actions decodes in its REST envelope,
    and ``SELECT metadata`` silently returns ``items: []``. Round-
    tripping through ``JSON_SERIALIZE`` forces the server's JSON
    parser to re-emit canonical OSON. Bare ``SET metadata = metadata``
    is COW-skipped and does NOT re-encode.

    Workaround for the driver/ORDS dialect mismatch; remove when
    either side is upgraded to bridge it.
    """
    LOGGER.info("Re-encoding metadata OSON server-side on %s", table_name)
    with db_conn.cursor() as cur:
        cur.execute(f'UPDATE "{table_name}" SET metadata = JSON_SERIALIZE(metadata)')
    db_conn.commit()


def _merge_and_index_vector_store(
    db_conn: oracledb.Connection,
    vector_store: VectorStoreConfig,
    vector_store_tmp: VectorStoreConfig,
    embed_client: Embeddings,
    modified_filenames: Optional[list[str]] = None,
) -> None:
    """Merge temporary vector store into real one and create index."""
    if vector_store.vector_store is None:
        raise ValueError("vector_store.vector_store must be set")
    safe_name = validate_vs_table_name(vector_store.vector_store)
    if vector_store_tmp.vector_store is None:
        raise ValueError("vector_store_tmp.vector_store must be set")
    safe_tmp_name = validate_vs_table_name(vector_store_tmp.vector_store)
    strategy = vector_store.distance_strategy or DistanceStrategy.COSINE

    vs_real = OracleVS(
        client=db_conn,
        embedding_function=embed_client,
        table_name=safe_name,
        distance_strategy=strategy,
        query="AI Optimizer for Apps - Powered by Oracle",
    )

    vector_store_idx = f"{safe_name}_IDX"
    if vector_store.index_type == "HNSW":
        drop_index_if_exists(db_conn, vector_store_idx)

    # Delete stale chunks for modified files so the INSERT below replaces them
    if modified_filenames:
        LOGGER.info("Deleting stale chunks for %d modified files", len(modified_filenames))
        delete_sql = f"DELETE FROM \"{safe_name}\" WHERE JSON_VALUE(metadata, '$.filename') = :fname"
        with db_conn.cursor() as cur:
            cur.executemany(delete_sql, [{"fname": fn} for fn in modified_filenames])
        db_conn.commit()

    # Re-encode before the merge copies bytes into the real table.
    _normalize_metadata_oson(db_conn, safe_tmp_name)

    merge_sql = f"""
        INSERT INTO "{safe_name}" SELECT * FROM "{safe_tmp_name}" src
         WHERE NOT EXISTS (SELECT 1 FROM "{safe_name}" tgt WHERE tgt.ID = src.ID)
    """
    LOGGER.info("Merging %s into %s", vector_store_tmp.vector_store, vector_store.vector_store)
    with db_conn.cursor() as cur:
        cur.execute(merge_sql)
    db_conn.commit()

    # Drop temp table
    try:
        with db_conn.cursor() as cur:
            cur.execute(f'DROP TABLE "{safe_tmp_name}" PURGE')
    except oracledb.DatabaseError:
        pass

    LOGGER.info("Creating index on: %s", safe_name)
    try:
        params = {"idx_name": vector_store_idx, "idx_type": vector_store.index_type}
        create_index(db_conn, vs_real, params)
    except Exception as ex:
        LOGGER.error("Unable to create vector index: %s", ex)


def _populate_vs_sync(
    db_config: DatabaseConfig,
    vector_store: VectorStoreConfig,
    embed_client: Embeddings,
    input_data: Union[list[DoclingDocumentChunk], list[str]],
    rate_limit: int = 0,
    modified_filenames: Optional[list[str]] = None,
) -> None:
    """Synchronous vector store population pipeline.

    Creates a sync connection, stages documents in a temp table,
    embeds in batches, merges into the real table, and indexes.
    """
    unique_chunks = _prepare_documents(input_data)

    db_conn = create_sync_connection(db_config)
    try:
        vs_tmp, vector_store_tmp = _create_temp_vector_store(db_conn, vector_store, embed_client)
        _embed_documents_in_batches(vs_tmp, unique_chunks, rate_limit)
        _merge_and_index_vector_store(db_conn, vector_store, vector_store_tmp, embed_client, modified_filenames)
    finally:
        db_conn.close()


# ---------------------------------------------------------------------------
# Async public API
# ---------------------------------------------------------------------------


async def populate_vs(
    db_config: DatabaseConfig,
    vector_store: VectorStoreConfig,
    embed_client: Embeddings,
    input_data: Union[list[DoclingDocumentChunk], list[str]],
    rate_limit: int = 0,
    modified_filenames: Optional[list[str]] = None,
) -> None:
    """Populate the vector store (async wrapper around sync OracleVS operations)."""
    await asyncio.to_thread(
        _populate_vs_sync,
        db_config,
        vector_store,
        embed_client,
        input_data,
        rate_limit,
        modified_filenames,
    )


async def update_vs_comment(
    conn: oracledb.AsyncConnection,
    vector_store: VectorStoreConfig,
    comment_json: str,
) -> None:
    """Update the GENAI comment on an existing vector store table."""
    if vector_store.vector_store is None:
        raise ValueError("vector_store.vector_store must be set")
    safe_name = validate_vs_table_name(vector_store.vector_store)
    # COMMENT ON TABLE is DDL — Oracle accepts no bind variables for either
    # the identifier or the body, so escape both manually.
    safe_comment = comment_json.replace("'", "''")
    sql = f"COMMENT ON TABLE \"{safe_name}\" IS 'GENAI: {safe_comment}'"
    await execute_sql(conn, sql)


async def get_vector_store_by_alias(
    conn: oracledb.AsyncConnection,
    alias: str,
) -> VectorStoreConfig:
    """Retrieve vector store configuration by alias from table comments.

    Delegates to :func:`discover_vector_stores` for SQL and legacy field
    mapping, then filters by alias.
    """
    stores = await discover_vector_stores(conn)
    for store in stores:
        if store.alias == alias:
            return store
    # Fallback: try matching by table name for legacy alias-less stores
    for store in stores:
        if store.vector_store == alias:
            return store
    raise ValueError(f"Vector store with alias '{alias}' not found")


async def get_total_chunks_count(
    conn: oracledb.AsyncConnection,
    vector_store_name: str,
) -> int:
    """Get total number of chunks in the vector store."""
    safe_name = validate_vs_table_name(vector_store_name)
    try:
        rows = await execute_sql(conn, f'SELECT COUNT(*) FROM "{safe_name}"')
        return rows[0][0] if rows else 0
    except Exception as ex:
        LOGGER.warning("Could not count chunks in %s: %s", vector_store_name, ex)
        return 0


async def get_processed_objects_metadata(
    conn: oracledb.AsyncConnection,
    vector_store_name: str,
) -> dict:
    """Get metadata of previously processed objects for a vector store.

    Aggregates server-side so result-set size is one row per file rather than
    one row per chunk — bounding API memory regardless of corpus size.
    """
    safe_name = validate_vs_table_name(vector_store_name)
    try:
        LOGGER.info("Retrieving metadata from %s", vector_store_name)
        new_format_sql = (
            "SELECT JSON_VALUE(metadata, '$.filename'),"
            " MAX(JSON_VALUE(metadata, '$.etag')),"
            " MAX(JSON_VALUE(metadata, '$.time_modified')),"
            " MAX(JSON_VALUE(metadata, '$.size'))"
            f' FROM "{safe_name}"'
            " WHERE JSON_VALUE(metadata, '$.filename') IS NOT NULL"
            " GROUP BY JSON_VALUE(metadata, '$.filename')"
        )
        rows = await execute_sql(conn, new_format_sql)

        processed_objects: dict = {}
        if rows:
            for filename, etag, time_modified, size_str in rows:
                processed_objects[filename] = {
                    "etag": etag,
                    "time_modified": time_modified,
                    "size": int(size_str) if size_str is not None else None,
                }
            LOGGER.info(
                "Found %i previously processed objects (new format) in %s",
                len(processed_objects),
                vector_store_name,
            )
            return processed_objects

        LOGGER.info("No filename field found, trying old format with 'source' field")
        legacy_sql = (
            "SELECT DISTINCT JSON_VALUE(metadata, '$.source')"
            f' FROM "{safe_name}"'
            " WHERE JSON_VALUE(metadata, '$.source') IS NOT NULL"
        )
        legacy_rows = await execute_sql(conn, legacy_sql)
        if legacy_rows:
            for (source,) in legacy_rows:
                processed_objects[os.path.basename(source)] = {
                    "etag": None,
                    "time_modified": None,
                    "size": None,
                }
            LOGGER.info(
                "Found %s previously processed objects (old format) in %s",
                len(processed_objects),
                vector_store_name,
            )
        else:
            LOGGER.info("No previously processed objects found in %s", vector_store_name)
        return processed_objects

    except ResultSetTooLargeError:
        # Surfacing this is correctness-critical: an empty fallback would
        # cause refresh to classify every bucket object as new, skip the
        # stale-chunk DELETE, and leave outdated embeddings in place.
        raise
    except Exception as ex:
        LOGGER.warning("Could not retrieve processed objects metadata from %s: %s", vector_store_name, ex)
        return {}


async def get_vector_store_files(
    conn: oracledb.AsyncConnection,
    vector_store_name: str,
) -> dict:
    """Get list of files embedded in a vector store with statistics.

    Aggregates server-side: one result row per ``(filename, source)`` pair
    rather than per chunk, so the API process never materializes per-chunk
    metadata regardless of corpus size.
    """
    safe_name = validate_vs_table_name(vector_store_name)
    LOGGER.info("Retrieving file list from %s", vector_store_name)
    sql = (
        "SELECT JSON_VALUE(metadata, '$.filename'),"
        " JSON_VALUE(metadata, '$.source'),"
        " COUNT(*),"
        " MAX(JSON_VALUE(metadata, '$.etag')),"
        " MAX(JSON_VALUE(metadata, '$.time_modified')),"
        " MAX(JSON_VALUE(metadata, '$.size'))"
        f' FROM "{safe_name}"'
        " GROUP BY JSON_VALUE(metadata, '$.filename'),"
        " JSON_VALUE(metadata, '$.source')"
    )
    rows = await execute_sql(conn, sql)
    if not rows:
        return {
            "vector_store": vector_store_name,
            "total_files": 0,
            "total_chunks": 0,
            "orphaned_chunks": 0,
            "files": [],
        }

    files_info: dict = {}
    total_identified_chunks = 0
    orphaned_chunks = 0

    for filename_raw, source_raw, raw_count, etag, time_modified, size_str in rows:
        count = int(raw_count)

        filename = filename_raw or (os.path.basename(source_raw) if source_raw else None)
        if not filename:
            orphaned_chunks += count
            continue

        size_value = int(size_str) if size_str is not None else None
        existing = files_info.get(filename)
        if existing is None:
            files_info[filename] = {
                "filename": filename,
                "chunk_count": count,
                "etag": etag,
                "time_modified": time_modified,
                "size": size_value,
            }
        else:
            # Same filename arrived from both new + legacy metadata rows; merge.
            existing["chunk_count"] += count
            existing["etag"] = existing["etag"] or etag
            existing["time_modified"] = existing["time_modified"] or time_modified
            if existing["size"] is None:
                existing["size"] = size_value
        total_identified_chunks += count

    file_list = sorted(files_info.values(), key=lambda x: x["filename"])

    result = {
        "vector_store": vector_store_name,
        "total_files": len(file_list),
        "total_chunks": total_identified_chunks,
        "orphaned_chunks": orphaned_chunks,
        "files": file_list,
    }

    if orphaned_chunks > 0:
        LOGGER.warning("Found %s orphaned chunks in %s", orphaned_chunks, vector_store_name)

    LOGGER.info(
        "Found %s files with %s total chunks in %s",
        len(file_list),
        total_identified_chunks + orphaned_chunks,
        vector_store_name,
    )
    return result
