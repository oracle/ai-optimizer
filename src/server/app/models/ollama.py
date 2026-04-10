"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Ollama model discovery — queries a running Ollama server for pulled models.
"""
# spell-checker: ignore ollama nomic

import logging
import os

import httpx

from server.app.core.settings import settings
from server.app.models.connectivity import CONNECT_TIMEOUT, READ_TIMEOUT, _normalize_ollama_name
from server.app.models.registry import _model_key, register_model
from server.app.models.schemas import ModelConfig

LOGGER = logging.getLogger(__name__)

# Model families (from /api/tags details.families) that are embedding models.
_EMBED_FAMILIES = {"bert", "nomic-bert"}


def _is_embedding_model(entry: dict) -> bool:
    """Return True if the Ollama model entry is an embedding model."""
    families = entry.get("details", {}).get("families") or []
    return any(f.casefold() in _EMBED_FAMILIES for f in families)


async def _get_context_length(client: httpx.AsyncClient, api_base: str, model_name: str) -> int | None:
    """Query ``/api/show`` for a model's context length."""
    try:
        resp = await client.post(f"{api_base.rstrip('/')}/api/show", json={"name": model_name})
        resp.raise_for_status()
        info = resp.json().get("model_info", {})
        arch = info.get("general.architecture", "")
        return info.get(f"{arch}.context_length")
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        LOGGER.debug("Failed to get context length for '%s': %s", model_name, exc)
        return None


async def _register_discovered_model(
    client: httpx.AsyncClient,
    api_base: str,
    entry: dict,
    existing: dict[tuple[str, str], ModelConfig],
    discovered_keys: set[tuple[str, str]],
) -> None:
    """Register a single discovered Ollama model, preserving existing overrides."""
    name = _normalize_ollama_name(entry["name"])
    key = _model_key(name, "ollama")
    discovered_keys.add(key)

    if key in existing:
        existing[key].api_base = api_base
        LOGGER.debug("Ollama model '%s' already configured — preserving settings", name)
        return

    model_type = "embed" if _is_embedding_model(entry) else "ll"
    model_dict: dict = {
        "id": name,
        "provider": "ollama",
        "type": model_type,
        "api_base": api_base,
        "enabled": True,
    }

    ctx_len = await _get_context_length(client, api_base, entry["name"])
    if ctx_len is not None:
        if model_type == "embed":
            model_dict["max_chunk_size"] = ctx_len
        else:
            model_dict["max_input_tokens"] = ctx_len

    register_model(ModelConfig(**model_dict))


async def load_ollama_models() -> None:
    """Discover pulled models from an Ollama server and register them.

    The server URL is read from ``AIO_ON_PREM_OLLAMA_URL`` or
    ``ON_PREM_OLLAMA_URL``.  When neither is set this function is a no-op.
    """
    api_base = os.getenv("AIO_ON_PREM_OLLAMA_URL") or os.getenv("ON_PREM_OLLAMA_URL")
    if not api_base:
        return

    # Always update api_base on existing ollama models so env var changes
    # take effect even when the server is temporarily unreachable.
    for m in settings.model_configs:
        if m.provider and m.provider.casefold() == "ollama":
            m.api_base = api_base

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)) as client:
            resp = await client.get(f"{api_base.rstrip('/')}/api/tags")
            resp.raise_for_status()
            data = resp.json()

            # Index persisted ollama configs so we can preserve user overrides
            existing: dict[tuple[str, str], ModelConfig] = {}
            for m in settings.model_configs:
                if m.id and m.provider and m.provider.casefold() == "ollama":
                    existing[_model_key(m.id, m.provider)] = m

            # Register discovered models
            discovered_keys: set[tuple[str, str]] = set()
            models = data.get("models", [])
            for entry in models:
                await _register_discovered_model(client, api_base, entry, existing, discovered_keys)

    except (httpx.HTTPError, ValueError) as exc:
        LOGGER.warning("Failed to discover Ollama models at %s: %s", api_base, exc)
        return

    # Remove ollama models that are no longer pulled
    removed = [k for k in existing if k not in discovered_keys]
    if removed:
        settings.model_configs = [
            m
            for m in settings.model_configs
            if not m.id
            or not m.provider
            or m.provider.casefold() != "ollama"
            or _model_key(m.id, m.provider) in discovered_keys
        ]
        LOGGER.info("Removed %d Ollama model(s) no longer pulled", len(removed))

    LOGGER.info("Discovered %d Ollama model(s) at %s", len(models), api_base)
