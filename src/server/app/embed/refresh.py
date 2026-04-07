"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Refresh vector store from OCI Object Storage bucket.
"""

import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path

from langchain_core.embeddings.embeddings import Embeddings

from server.app.database.schemas import DatabaseConfig
from server.app.embed.schemas import VectorStoreConfig
from server.app.oci.bucket import download_object, flatten_bucket_key
from server.app.oci.schemas import OciProfileConfig

from .document import load_and_split_documents
from .vector_store import populate_vs

LOGGER = logging.getLogger(__name__)


async def refresh_vector_store_from_bucket(
    vector_store_config: VectorStoreConfig,
    bucket_name: str,
    bucket_objects: list[dict],
    db_config: DatabaseConfig,
    embed_client: Embeddings,
    oci_profile: OciProfileConfig,
    rate_limit: int = 0,
    modified_objects: list[dict] | None = None,
    parsing_mode: str = "fast",
) -> dict:
    """Refresh a vector store with new/modified objects from an OCI bucket.

    Downloads changed objects, processes them through the document pipeline,
    and populates the vector store.

    Returns:
        Dict with processing results (processed_files, total_chunks, message, errors).
    """
    if not bucket_objects:
        return {
            "processed_files": 0,
            "new_files": 0,
            "updated_files": 0,
            "total_chunks": 0,
            "message": "No new or modified files to process",
        }

    temp_directory = Path(tempfile.mkdtemp(prefix="refresh_"))
    LOGGER.info("Processing %d objects for vector store refresh", len(bucket_objects))

    try:
        # Download changed objects
        downloaded_files: list[str] = []
        download_errors: list[str] = []
        for obj in bucket_objects:
            try:
                downloaded_files.append(
                    await asyncio.to_thread(download_object, str(temp_directory), obj["name"], bucket_name, oci_profile)
                )
            except Exception:
                LOGGER.exception("Failed to download object %s", obj["name"])
                download_errors.append(f"Failed to download: {obj['name']}")
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

        # Derive modified_filenames from only successfully downloaded files
        # to avoid deleting chunks for files that failed to re-download
        modified_filenames = None
        if modified_objects:
            downloaded_basenames = {os.path.basename(f) for f in downloaded_files}
            modified_filenames = [
                flattened_name
                for flattened_name in (flatten_bucket_key(obj["name"]) for obj in modified_objects)
                if flattened_name in downloaded_basenames
            ] or None

        LOGGER.info("Preparing metadata for %d bucket objects", len(bucket_objects))

        # Process documents with metadata
        if vector_store_config.embedding_model is None:
            raise ValueError("vector_store_config.embedding_model must be set")
        split_docos, _, _ = await asyncio.to_thread(
            load_and_split_documents,
            downloaded_files,
            f"{vector_store_config.embedding_model.provider}/{vector_store_config.embedding_model.id}",
            vector_store_config.chunk_size or 0,
            vector_store_config.chunk_overlap or 0,
            write_json=False,
            output_dir=None,
            file_metadata={
                flatten_bucket_key(obj["name"]): {
                    "size": int(obj["size"]) if obj.get("size") is not None else None,
                    "time_modified": obj.get("time_modified"),
                    "etag": obj.get("etag"),
                    "bucket_name": bucket_name,
                }
                for obj in bucket_objects
            },
            parsing_mode=parsing_mode,
        )

        LOGGER.info("Processed %s document chunks with OCI bucket metadata", len(split_docos))

        # Populate vector store
        await populate_vs(
            db_config=db_config,
            vector_store=vector_store_config,
            embed_client=embed_client,
            input_data=split_docos,
            rate_limit=rate_limit,
            modified_filenames=modified_filenames,
        )

        return {
            "processed_files": len(downloaded_files),
            "new_files": len(downloaded_files) - (len(modified_filenames) if modified_filenames else 0),
            "updated_files": len(modified_filenames) if modified_filenames else 0,
            "total_chunks": len(split_docos),
            "message": f"Successfully processed {len(downloaded_files)} files and {len(split_docos)} chunks",
            "errors": download_errors,
        }

    finally:
        if temp_directory.exists():
            shutil.rmtree(temp_directory)
