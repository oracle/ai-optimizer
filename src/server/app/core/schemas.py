"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pydantic models for per-client session settings.
"""

from typing import Optional

from pydantic import BaseModel

from server.app.embed.schemas import IndexTypes
from server.app.models.schemas import LanguageModelParameters, ModelIdentity

# Canonical tool names (must match client-side values)
TOOL_VECSEARCH = "Vector Search"
TOOL_NL2SQL = "NL2SQL"


class LLModelSettings(LanguageModelParameters, ModelIdentity):
    """Client language-model settings."""

    chat_history: bool = True


class OciSettings(BaseModel):
    """Client OCI profile reference."""

    auth_profile: str = "DEFAULT"


class DatabaseSettings(BaseModel):
    """Client database reference."""

    alias: str = "CORE"


class VectorSearchSettings(ModelIdentity):
    """Client vector-search configuration."""

    vector_store: Optional[str] = None
    alias: Optional[str] = None
    description: Optional[str] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    distance_strategy: Optional[str] = None
    index_type: Optional[IndexTypes] = None
    discovery: bool = True
    rephrase: bool = True
    grade: bool = True
    search_type: str = "Similarity"
    top_k: int = 8
    score_threshold: float = 0.65
    fetch_k: int = 20
    lambda_mult: float = 0.5


class TestbedSettings(BaseModel):
    """Client testbed model references."""

    qa_ll_model: Optional[ModelIdentity] = None
    qa_embed_model: Optional[ModelIdentity] = None
    judge_model: Optional[ModelIdentity] = None


class DeepDataSecuritySettings(BaseModel):
    """Client Deep Data Security 'connect as' override.

    Runtime/session-scoped only — never persisted or exported. When ``enabled``
    and ``base_alias`` matches the active database, chat-time read tools (Vector
    Search, NL2SQL) connect through the managed ``alias`` (which authenticates as
    the DDS end user) instead of the schema owner.
    """

    enabled: bool = False
    end_user: Optional[str] = None
    alias: Optional[str] = None
    base_alias: Optional[str] = None


class ClientSettings(BaseModel):
    """Per-client session settings."""

    client: str = "CONFIGURED"
    ll_model: LLModelSettings = LLModelSettings()
    oci: OciSettings = OciSettings()
    database: DatabaseSettings = DatabaseSettings()
    tools_enabled: list[str] = []
    vector_search: VectorSearchSettings = VectorSearchSettings()
    testbed: TestbedSettings = TestbedSettings()
    deep_data_security: DeepDataSecuritySettings = DeepDataSecuritySettings()


class HelpItem(BaseModel):
    """Single help-text entry."""

    key: str
    text: str


class ClientSettingsUpdate(BaseModel):
    """Partial update payload for client settings."""

    model_config = {
        "json_schema_extra": {
            "example": {
                "ll_model": {
                    "provider": "openai",
                    "id": "gpt-5.4-mini",
                    "temperature": 0.3,
                    "max_tokens": 4096,
                    "chat_history": True,
                },
                "database": {"alias": "CORE"},
                "oci": {"auth_profile": "DEFAULT"},
                "tools_enabled": [TOOL_VECSEARCH],
                "vector_search": {
                    "provider": "openai",
                    "id": "text-embedding-3-small",
                    "alias": "PRODUCT_DOCS",
                    "top_k": 8,
                    "score_threshold": 0.65,
                },
            }
        }
    }

    ll_model: Optional[LLModelSettings] = None
    oci: Optional[OciSettings] = None
    database: Optional[DatabaseSettings] = None
    tools_enabled: Optional[list[str]] = None
    vector_search: Optional[VectorSearchSettings] = None
    testbed: Optional[TestbedSettings] = None
    deep_data_security: Optional[DeepDataSecuritySettings] = None
