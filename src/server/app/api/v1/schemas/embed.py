"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pydantic models for embed API request/response schemas.
"""

from typing import Optional

from pydantic import BaseModel


class SqlStoreRequest(BaseModel):
    """Request body for storing SQL query results for embedding."""

    model_config = {
        "json_schema_extra": {
            "example": {
                "query": "SELECT product_id, description FROM products WHERE active = 1",
                "db_alias": "CORE",
            }
        }
    }

    query: str
    db_alias: Optional[str] = None


class VectorStoreRefreshRequest(BaseModel):
    """Request body for refreshing a vector store from an OCI bucket."""

    model_config = {
        "json_schema_extra": {
            "example": {
                "vector_store_alias": "PRODUCT_DOCS",
                "bucket_name": "rag-source-docs",
                "auth_profile": "DEFAULT",
                "rate_limit": 0,
                "parsing_mode": "fast",
            }
        }
    }

    vector_store_alias: str
    bucket_name: str
    auth_profile: Optional[str] = "DEFAULT"
    rate_limit: Optional[int] = 0
    parsing_mode: Optional[str] = "fast"


class VectorStoreRefreshStatus(BaseModel):
    """Response body for vector store refresh status."""

    status: str
    message: str
    processed_files: int
    new_files: int
    updated_files: int
    total_chunks: int
    total_chunks_in_store: int = 0
    errors: list[str] = []


class ProcessedFileInfo(BaseModel):
    """Info about a successfully processed file."""

    filename: str
    chunks: int


class SkippedFileInfo(BaseModel):
    """Info about a skipped file."""

    filename: str
    reason: str


class EmbedProcessingResult(BaseModel):
    """Response body for the split-and-embed operation."""

    message: str
    total_chunks: int
    processed_files: list[ProcessedFileInfo]
    skipped_files: list[SkippedFileInfo]
