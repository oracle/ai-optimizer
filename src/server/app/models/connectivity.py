"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Model endpoint reachability checks run at startup.
"""
# spell-checker: ignore ollama vllm huggingface

import asyncio
import logging
import os

import httpx

from server.app.core.settings import settings

LOGGER = logging.getLogger(__name__)

NO_KEY_PROVIDERS = {"ollama", "huggingface", "hosted_vllm"}
CONNECT_TIMEOUT = 3.0
READ_TIMEOUT = 5.0


def ollama_server_url() -> str | None:
    """Configured Ollama server URL, or None when no Ollama server is configured."""
    return os.getenv("AIO_ON_PREM_OLLAMA_URL") or os.getenv("ON_PREM_OLLAMA_URL")


def _normalize_ollama_name(name: str) -> str:
    """Strip the ``':latest'`` tag so ``'llama3.1:latest'`` matches ``'llama3.1'``."""
    return name[: -len(":latest")] if name.endswith(":latest") else name


# Providers whose model ids carry an Ollama-style ``':latest'`` tag.
_OLLAMA_PROVIDERS = {"ollama", "ollama_chat"}


def canonical_model_id(provider: str | None, model_id: str | None) -> str:
    """Return the identity-normalized model id.

    For Ollama the ``':latest'`` tag is folded out so ``foo`` and ``foo:latest``
    resolve to one model — the same rule ``find_model`` applies on lookup. Used by
    the registry dedupe and the settings import/merge identity so every path agrees
    on what counts as the same model.
    """
    model_id = model_id or ""
    if (provider or "").casefold() in _OLLAMA_PROVIDERS:
        return _normalize_ollama_name(model_id)
    return model_id


async def _fetch_ollama_models(client: httpx.AsyncClient, api_base: str) -> set[str] | None:
    """Return the set of model names available on an Ollama server, or *None* on failure."""
    try:
        resp = await client.get(f"{api_base.rstrip('/')}/api/tags")
        resp.raise_for_status()
        data = resp.json()
        names = {_normalize_ollama_name(m["name"]).casefold() for m in data.get("models", [])}
        LOGGER.debug("Ollama at %s has models: %s", api_base, names)
        return names
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        LOGGER.debug("Failed to fetch Ollama model list from %s: %s", api_base, exc)
        return None


async def _apply_ollama_rules(client: httpx.AsyncClient, ollama_models: list) -> None:
    """Rule 6: Only enable Ollama models that are actually pulled."""
    by_base: dict[str, list] = {}
    for model in ollama_models:
        # A config with no api_base (e.g. imported, or loaded while Ollama was down so
        # discovery couldn't populate it) defaults to the configured server — mirroring
        # check_single_model — so a later recheck recovers it once Ollama comes online,
        # instead of being pinned unreachable forever.
        if not model.api_base:
            model.api_base = ollama_server_url()
        if not model.api_base:
            model.status = "unreachable"
            continue
        by_base.setdefault(model.api_base, []).append(model)

    for api_base, models in by_base.items():
        available = await _fetch_ollama_models(client, api_base)
        if available is None:
            for model in models:
                model.status = "unreachable"
                LOGGER.debug("Model '%s' (ollama) unreachable at %s", model.id, api_base)
            continue

        for model in models:
            normalized_id = _normalize_ollama_name(model.id).casefold()
            if normalized_id in available:
                model.status = "available"
                LOGGER.debug("Model '%s' (ollama) available at %s", model.id, api_base)
            else:
                # Server is up but the model isn't pulled — the one state where Pull applies.
                model.status = "not_pulled"
                LOGGER.debug("Model '%s' (ollama) not pulled at %s", model.id, api_base)


async def _probe_endpoint(client: httpx.AsyncClient, api_base: str) -> tuple[bool, str | None]:
    """HEAD-probe *api_base*; any HTTP response means reachable."""
    try:
        resp = await client.head(api_base)
        LOGGER.debug("Probe %s -> HTTP %s", api_base, resp.status_code)
        return True, None
    except httpx.HTTPError as exc:
        LOGGER.debug("Probe %s failed: %s", api_base, exc)
        return False, str(exc)


def _apply_oci_rules(oci_models: list) -> None:
    """Rule 5: OCI models require a usable OCI profile."""
    has_usable_oci = any(p.usable for p in settings.oci_configs)
    for model in oci_models:
        if has_usable_oci:
            model.status = "available"
            LOGGER.debug("Model '%s' (oci) available via OCI profile", model.id)
        else:
            # Leave ``enabled`` (user intent) alone — like every other rule — so the
            # model recovers automatically once a usable OCI profile is added.
            model.status = "unreachable"
            LOGGER.debug("Model '%s' (oci) unreachable — no usable OCI profile", model.id)


def _apply_probe_rules(to_probe: dict, results: dict) -> None:
    """Apply reachability rules 1-4 to probed endpoints."""
    for api_base, models in to_probe.items():
        reachable, error = results[api_base]
        for model in models:
            provider = (model.provider or "").casefold()
            if not reachable:
                # Rule 1
                model.status = "unreachable"
                LOGGER.debug("Model '%s' (%s) unreachable at %s: %s", model.id, provider, api_base, error)
            elif model.api_key:
                # Rule 2
                model.status = "available"
                LOGGER.debug("Model '%s' (%s) available (key present)", model.id, provider)
            elif provider in NO_KEY_PROVIDERS:
                # Rule 3
                model.status = "available"
                LOGGER.debug("Model '%s' (%s) available (no key required)", model.id, provider)
            else:
                # Rule 4
                model.status = "no_key"
                LOGGER.debug("Model '%s' (%s) reachable but no api_key", model.id, provider)


def _log_model_summary() -> None:
    """Log a one-line count of loaded / available / enabled models."""
    LOGGER.info(
        "Models Loaded: %d; Models Available: %d; Models Enabled: %d",
        len(settings.model_configs),
        sum(1 for m in settings.model_configs if m.status == "available"),
        sum(1 for m in settings.model_configs if m.enabled),
    )


async def check_model_reachability() -> None:
    """Verify enabled models can reach their endpoints and set ``status``."""
    enabled = [m for m in settings.model_configs if m.enabled]
    if not enabled:
        _log_model_summary()
        return

    # --- Rule 5: OCI models without an enabled OCI profile ---
    oci_models = [m for m in enabled if m.provider and m.provider.casefold() == "oci"]
    non_oci = [m for m in enabled if not m.provider or m.provider.casefold() != "oci"]
    _apply_oci_rules(oci_models)

    # --- Rule 6: Ollama models — verify pulled ---
    ollama_models = [m for m in non_oci if (m.provider or "").casefold() == "ollama"]
    non_ollama = [m for m in non_oci if (m.provider or "").casefold() != "ollama"]

    # --- Collect endpoints to probe (deduplicate by api_base) ---
    to_probe: dict[str, list] = {}  # api_base -> list of models
    for model in non_ollama:
        if not model.api_base:
            LOGGER.debug("Model '%s' (%s) has no api_base — marking unreachable", model.id, model.provider)
            model.status = "unreachable"
            continue
        to_probe.setdefault(model.api_base, []).append(model)

    if not to_probe and not ollama_models:
        _log_model_summary()
        return

    # --- Probe unique endpoints in parallel + verify Ollama models ---
    async with httpx.AsyncClient(timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)) as client:
        if ollama_models:
            await _apply_ollama_rules(client, ollama_models)
        tasks = {url: _probe_endpoint(client, url) for url in to_probe}
        results = dict(zip(tasks.keys(), await asyncio.gather(*tasks.values())))

    _apply_probe_rules(to_probe, results)

    _log_model_summary()


async def check_single_model(model) -> None:
    """Probe a single model and set its ``status``.

    Called when a model is created or updated via the API so that the caller
    does not have to restart the server.
    """
    if not model.enabled:
        model.status = "unreachable"
        return

    provider = (model.provider or "").casefold()

    # OCI models — delegate to existing rule (no api_base required)
    if provider == "oci":
        _apply_oci_rules([model])
        return

    # A manually added Ollama model has no api_base; default it to the configured server
    # so it can be probed (and offered for Pull) immediately, not only after discovery runs.
    if provider == "ollama" and not model.api_base:
        model.api_base = ollama_server_url()

    # All other providers need an api_base to be reachable.
    if not model.api_base:
        model.status = "unreachable"
        return

    # Ollama models — verify the model is actually pulled
    if provider == "ollama":
        async with httpx.AsyncClient(timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)) as client:
            await _apply_ollama_rules(client, [model])
        return

    async with httpx.AsyncClient(timeout=httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)) as client:
        reachable, error = await _probe_endpoint(client, model.api_base)

    if not reachable:
        model.status = "unreachable"
        LOGGER.debug("Model '%s' (%s) unreachable at %s: %s", model.id, provider, model.api_base, error)
    elif model.api_key or provider in NO_KEY_PROVIDERS:
        model.status = "available"
    else:
        model.status = "no_key"

    LOGGER.info("Model '%s' (%s) status=%s", model.id, provider, model.status)
