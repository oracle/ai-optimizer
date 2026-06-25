"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared response models and helper functions for MCP vector-search tools.
"""
# spell-checker:ignore hnsw genai

import logging
from typing import Optional

from pydantic import BaseModel

from server.app.core.settings import resolve_client, settings
from server.app.database.config import get_tool_pool
from server.app.embed.schemas import VectorStoreConfig
from server.app.oci.schemas import OciProfileConfig

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------
class VectorTable(BaseModel):
    """Information about a discovered vector table."""

    table_name: str
    table_comment: Optional[str] = None
    parsed: VectorStoreConfig


class VectorStoreListResponse(BaseModel):
    """Response from the optimizer_vs_discovery tool."""

    parsed_tables: list[VectorTable]
    status: str
    error: Optional[str] = None


class VectorGradeResponse(BaseModel):
    """Response from the optimizer_vs_grade tool."""

    relevant: str
    formatted_documents: str
    grading_performed: bool
    num_documents: int
    status: str
    error: Optional[str] = None


class RephrasePrompt(BaseModel):
    """Response from the optimizer_vs_rephrase tool."""

    original_prompt: str
    rephrased_prompt: str
    was_rephrased: bool
    status: str
    error: Optional[str] = None


class VectorSearchResponse(BaseModel):
    """Response from the optimizer_vs_retriever tool."""

    context_input: str
    documents: list[dict]
    num_documents: int
    searched_tables: list[str]
    failed_tables: list[str] = []
    status: str
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_oci_profile(client: str = "CONFIGURED") -> Optional[OciProfileConfig]:
    """Resolve the OCI profile from ``settings``."""
    profile_name = resolve_client(client).oci.auth_profile
    for cfg in settings.oci_configs:
        if cfg.auth_profile == profile_name:
            return cfg
    return None


def get_database_pool(client: str = "CONFIGURED"):
    """Resolve the async connection pool for the client's chat-time read tools.

    DDS-aware: when the client's Deep Data Security 'connect as' override is active this
    returns the managed end-user pool; it raises ``DdsConnectionError`` when the override is
    active but its connection is unusable (never falls back to the schema owner).
    """
    return get_tool_pool(client)
