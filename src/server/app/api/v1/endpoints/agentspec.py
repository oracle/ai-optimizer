"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Agent spec endpoints — export and inspect pyagentspec definitions.

Exposes portable AgentSpec definitions as serialized JSON so developers
can inspect, customize, and load them into any compatible runtime.
"""

# spell-checker: ignore mydb agentspec ollama pyagentspec vecsearch litellm
import json
import logging

from fastapi import APIRouter, HTTPException
from pyagentspec.serialization import AgentSpecSerializer

from server.app.agentspec.adapters.litellm import get_litellm_serialization_plugin
from server.app.agentspec.agent_llm_only import build_llm_only_agentspec
from server.app.agentspec.agent_nl2sql import build_nl2sql_agentspec
from server.app.agentspec.flow_vecsearch import build_vecsearch_flow
from server.app.api.v1.schemas.agents import AgentSpecResponse
from server.app.core.schemas import ClientSettings, DatabaseSettings, LLModelSettings, VectorSearchSettings
from server.app.core.settings import settings

LOGGER = logging.getLogger(__name__)

auth = APIRouter(prefix="/agentspec")

# ---------------------------------------------------------------------------
# Sample values used to build showcase specs (not for execution).
# Developers can substitute their own provider, model, and MCP endpoint.
# ---------------------------------------------------------------------------

_SAMPLE_SERVER_URL = "http://localhost:8001/mcp"
_SAMPLE_API_KEY = "your-api-key"
_SAMPLE_PROMPT = "You are a helpful assistant."


def _sample_client_settings() -> ClientSettings:
    """Build showcase ClientSettings using an LL model from settings.

    Prefers an enabled LL model, otherwise uses any configured LL model so the
    spec still serializes for inspection. Falls back to an ollama/granite4.1:8b
    placeholder only when no LL model config exists at all.
    """
    ll_models = [c for c in settings.model_configs if c.type == "ll" and c.provider and c.id]
    chosen = next((c for c in ll_models if c.enabled), ll_models[0] if ll_models else None)
    provider = chosen.provider if chosen else "ollama"
    model_id = chosen.id if chosen else "granite4.1:8b"
    return ClientSettings(
        ll_model=LLModelSettings(
            provider=provider,
            id=model_id,
            max_tokens=1024,
            temperature=0.1,
        ),
        database=DatabaseSettings(alias="MYDB"),
        vector_search=VectorSearchSettings(
            discovery=True,
            rephrase=True,
            grade=True,
            search_type="Similarity",
            top_k=8,
            score_threshold=0.65,
        ),
    )


_serializer = AgentSpecSerializer(plugins=[get_litellm_serialization_plugin()])


def _serialize(component) -> dict:
    """Serialize an AgentSpec component to a JSON-safe dict."""
    return json.loads(_serializer.to_json(component))


def _build_llm_only() -> dict:
    return _serialize(build_llm_only_agentspec(_sample_client_settings(), _SAMPLE_PROMPT))


def _build_nl2sql_agent() -> dict:
    return _serialize(
        build_nl2sql_agentspec(_sample_client_settings(), _SAMPLE_SERVER_URL, _SAMPLE_API_KEY, _SAMPLE_PROMPT)
    )


def _build_vecsearch_flow() -> dict:
    return _serialize(
        build_vecsearch_flow(_sample_client_settings(), _SAMPLE_SERVER_URL, _SAMPLE_API_KEY, _SAMPLE_PROMPT)
    )


_SPEC_BUILDERS = {
    "llm_only": ("LLM-only conversational agent (no tools)", _build_llm_only),
    "nl2sql_agent": ("NL2SQL agent with dynamic MCP tool discovery", _build_nl2sql_agent),
    "vecsearch_flow": ("RAG pipeline: rephrase → retrieve → grade → answer", _build_vecsearch_flow),
}


@auth.get("/specs", response_model=list[AgentSpecResponse])
async def list_specs():
    """List all available agent spec definitions as serialized JSON."""
    results = []
    for name, (description, builder) in _SPEC_BUILDERS.items():
        try:
            spec = builder()
        except Exception:
            LOGGER.exception("Failed to build agentspec %r", name)
            spec = {"error": "Could not build spec — check server logs for details"}
        results.append(AgentSpecResponse(name=name, description=description, spec=spec))
    return results


@auth.get("/specs/{name}", response_model=AgentSpecResponse)
async def get_spec(name: str):
    """Get a specific agent spec definition by name."""
    if name not in _SPEC_BUILDERS:
        raise HTTPException(status_code=404, detail=f"Spec '{name}' not found. Available: {list(_SPEC_BUILDERS)}")
    description, builder = _SPEC_BUILDERS[name]
    try:
        spec = builder()
    except Exception:
        spec = {"error": "Could not build spec — check server logs for details"}
    return AgentSpecResponse(name=name, description=description, spec=spec)
