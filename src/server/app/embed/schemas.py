"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pydantic models for vector store and embedding configuration.
"""
# spell-checker: ignore vectorstores hnsw

from typing import Literal, Optional

from langchain_oracledb.vectorstores.oraclevs import DistanceStrategy
from pydantic import BaseModel, Field

from server.app.models.schemas import ModelIdentity

IndexTypes = Literal["HNSW", "IVF", "HYB"]
ParsingMode = Literal["fast", "deep"]


class VectorStoreConfig(BaseModel):
    """Vector store embedding configuration."""

    model_config = {
        "json_schema_extra": {
            "example": {
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

    vector_store: Optional[str] = Field(
        default=None,
        description="Vector Store Table Name (auto-generated, do not set)",
        json_schema_extra={"readOnly": True},
    )
    alias: Optional[str] = Field(default=None, description="Identifiable Alias")
    description: Optional[str] = Field(default=None, description="Human-readable description of table contents")
    embedding_model: Optional[ModelIdentity] = Field(default=None, description="Embedding Model")
    chunk_size: Optional[int] = Field(default=0, description="Chunk Size")
    chunk_overlap: Optional[int] = Field(default=0, description="Chunk Overlap")
    distance_strategy: Optional[DistanceStrategy] = Field(default=None, description="Distance Strategy")
    index_type: Optional[IndexTypes] = Field(default=None, description="Vector Index")
    parsing_mode: Optional[ParsingMode] = Field(default="fast", description="Document parsing mode")
