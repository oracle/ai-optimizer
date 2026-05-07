"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pydantic models for embed API request/response schemas.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel

from server.app.embed.schemas import VectorStoreConfig


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


class OciEmbedRequest(VectorStoreConfig):
    """Request body for the single-call OCI download + embed endpoint.

    ``objects`` is optional — when omitted (or empty) every supported
    object in *bucket_name* is embedded. When provided, only the listed
    keys are downloaded.
    """

    model_config = {
        "json_schema_extra": {
            "example": {
                "bucket_name": "rag-source-docs",
                "auth_profile": "DEFAULT",
                "objects": ["product-catalog.pdf", "release-notes/2026-q2.md"],
                "alias": "PRODUCT_DOCS",
                "description": "Product documentation embedded for RAG",
                "embedding_model": {"provider": "openai", "id": "text-embedding-3-small"},
                "chunk_size": 1024,
                "chunk_overlap": 128,
                "distance_strategy": "COSINE",
                "index_type": "HNSW",
                "parsing_mode": "fast",
            }
        }
    }

    bucket_name: str
    auth_profile: str = "DEFAULT"
    objects: Optional[list[str]] = None


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


class EmbedJobStatus(str, Enum):
    """Lifecycle states for a background embed job."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class EmbedJobStage(str, Enum):
    """Granular stage within a running embed job."""

    QUEUED = "queued"
    PREPARING = "preparing"
    SPLITTING = "splitting"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    FINALIZING = "finalizing"


class EmbedJobProgress(BaseModel):
    """Progress snapshot for a running embed job."""

    stage: EmbedJobStage
    message: Optional[str] = None
    total_chunks: Optional[int] = None


class EmbedJobAccepted(BaseModel):
    """202 response body returned when a split-and-embed job is scheduled."""

    job_id: str
    status: EmbedJobStatus
    location: str


class EmbedJobInfo(BaseModel):
    """Full status record for an embed job — returned by GET /v1/embed/jobs/{job_id}."""

    job_id: str
    status: EmbedJobStatus
    created_at: str
    updated_at: str
    progress: Optional[EmbedJobProgress] = None
    result: Optional[EmbedProcessingResult] = None
    error: Optional[str] = None
