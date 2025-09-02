"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

NOTE: Provide only one example per API to populate supported API lists; additional models should be
added via the APIs
"""
# spell-checker:ignore configfile genai ollama pplx docos mxbai nomic thenlper
# spell-checker:ignore huggingface

import os

from server.bootstrap.configfile import ConfigStore
from common.schema import Model
from common.functions import is_url_accessible
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("bootstrap.models")


def main() -> list[Model]:
    """Define example Model Support"""
    logger.debug("*** Bootstrapping Models - Start")

    models_list = [
        {
            "id": "command-r",
            "enabled": os.getenv("COHERE_API_KEY") is not None,
            "type": "ll",
            "provider": "cohere",
            "api_key": os.environ.get("COHERE_API_KEY", default=""),
            "openai_compat": False,
            "url": "https://api.cohere.ai",
            "context_length": 127072,
            "temperature": 0.3,
            "max_completion_tokens": 4096,
            "frequency_penalty": 0.0,
        },
        {
            "id": "gpt-4o-mini",
            "enabled": os.getenv("OPENAI_API_KEY") is not None,
            "type": "ll",
            "provider": "openai",
            "api_key": os.environ.get("OPENAI_API_KEY", default=""),
            "openai_compat": True,
            "url": "https://api.openai.com/v1",
            "context_length": 127072,
            "temperature": 1.0,
            "max_completion_tokens": 4096,
            "frequency_penalty": 0.0,
        },
        {
            "id": "sonar",
            "enabled": os.getenv("PPLX_API_KEY") is not None,
            "type": "ll",
            "provider": "perplexity",
            "api_key": os.environ.get("PPLX_API_KEY", default=""),
            "openai_compat": True,
            "url": "https://api.perplexity.ai",
            "context_length": 127072,
            "temperature": 0.2,
            "max_completion_tokens": 28000,
            "frequency_penalty": 1.0,
        },
        {
            "id": "phi-4",
            "enabled": False,
            "type": "ll",
            "provider": "openai_compatible",
            "api_key": "",
            "openai_compat": True,
            "url": "http://localhost:1234/v1",
            "context_length": 131072,
            "temperature": 1.0,
            "max_completion_tokens": 4096,
            "frequency_penalty": 0.0,
        },
        {
            "id": "gpt-oss:20b",
            "enabled": os.getenv("ON_PREM_OLLAMA_URL") is not None,
            "type": "ll",
            "provider": "ollama",
            "api_key": "",
            "openai_compat": True,
            "url": os.environ.get("ON_PREM_OLLAMA_URL", default="http://127.0.0.1:11434"),
            "context_length": 131072,
            "temperature": 1.0,
            "max_completion_tokens": 2048,
            "frequency_penalty": 0.0,
        },
        {
            # This is intentionally last to line up with docos
            "id": "meta-llama/Llama-3.2-1B-Instruct",
            "enabled": os.getenv("ON_PREM_VLLM_URL") is not None,
            "type": "ll",
            "provider": "openai_compatible",
            "api_key": "",
            "openai_compat": True,
            "url": os.environ.get("ON_PREM_VLLM_URL", default="http://gpu:8000/v1"),
            "context_length": 131072,
            "temperature": 1.0,
            "max_completion_tokens": 2048,
            "frequency_penalty": 0.0,
        },
        {
            # This is intentionally last to line up with docos
            "id": "llama3.1",
            "enabled": os.getenv("ON_PREM_OLLAMA_URL") is not None,
            "type": "ll",
            "provider": "ollama",
            "api_key": "",
            "openai_compat": True,
            "url": os.environ.get("ON_PREM_OLLAMA_URL", default="http://127.0.0.1:11434"),
            "context_length": 131072,
            "temperature": 1.0,
            "max_completion_tokens": 2048,
            "frequency_penalty": 0.0,
        },
        {
            "id": "thenlper/gte-base",
            "enabled": os.getenv("ON_PREM_HF_URL") is not None,
            "type": "embed",
            "provider": "huggingface",
            "url": os.environ.get("ON_PREM_HF_URL", default="http://127.0.0.1:8080"),
            "api_key": "",
            "openai_compat": True,
            "max_chunk_size": 512,
        },
        {
            "id": "text-embedding-3-small",
            "enabled": os.getenv("OPENAI_API_KEY") is not None,
            "type": "embed",
            "provider": "openai_compatible",
            "url": "https://api.openai.com/v1",
            "api_key": os.environ.get("OPENAI_API_KEY", default=""),
            "openai_compat": True,
            "max_chunk_size": 8191,
        },
        {
            "id": "embed-english-light-v3.0",
            "enabled": os.getenv("COHERE_API_KEY") is not None,
            "type": "embed",
            "provider": "cohere",
            "url": "https://api.cohere.ai",
            "api_key": os.environ.get("COHERE_API_KEY", default=""),
            "openai_compat": False,
            "max_chunk_size": 512,
        },
        {
            "id": "nomic-ai/nomic-embed-text-v1",
            "enabled": False,
            "type": "embed",
            "provider": "openai_compatible",
            "url": "http://localhost:1234/v1",
            "api_key": "",
            "openai_compat": True,
            "max_chunk_size": 8192,
        },
        {
            # This is intentionally last to line up with docos
            "id": "mxbai-embed-large",
            "enabled": os.getenv("ON_PREM_OLLAMA_URL") is not None,
            "type": "embed",
            "provider": "ollama",
            "url": os.environ.get("ON_PREM_OLLAMA_URL", default="http://127.0.0.1:11434"),
            "api_key": "",
            "openai_compat": True,
            "max_chunk_size": 8192,
        },
    ]

    # Check for duplicates
    unique_entries = set()
    for model in models_list:
        if model["id"] in unique_entries:
            raise ValueError(f"Model '{model['id']}' already exists.")
        unique_entries.add(model["id"])

    # Merge with configuration if available
    configuration = ConfigStore.get()
    if configuration and configuration.model_configs:
        logger.debug("Merging model configs from ConfigStore")
        config_model_map = {m.id: m.model_dump() for m in configuration.model_configs}
        existing = {m["id"]: m for m in models_list}

        def values_differ(a, b):
            if isinstance(a, bool) or isinstance(b, bool):
                return bool(a) != bool(b)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                return abs(a - b) > 1e-8
            if isinstance(a, str) and isinstance(b, str):
                return a.strip() != b.strip()
            return a != b

        for model_id, override in config_model_map.items():
            if model_id in existing:
                for k, v in override.items():
                    if k not in existing[model_id]:
                        continue
                    if values_differ(existing[model_id][k], v):
                        log_func = logger.debug if k == "api_key" else logger.info
                        log_func(
                            "Overriding field '%s' for model '%s' (was: %r → now: %r)",
                            k,
                            model_id,
                            existing[model_id][k],
                            v,
                        )
                        existing[model_id][k] = v
            else:
                logger.info("Adding new model from ConfigStore: %s", model_id)
                existing[model_id] = override

        models_list = list(existing.values())

    # Override with OS env vars (by API type)
    for model in models_list:
        provider = model.get("provider", "")
        model_id = model.get("id", "")
        overridden = False

        if provider == "cohere" and os.getenv("COHERE_API_KEY"):
            old_api_key = model.get("api_key", "")
            new_api_key = os.environ["COHERE_API_KEY"]
            if old_api_key != new_api_key:
                # Exposes key if in DEBUG
                logger.debug("Overriding 'api_key' for model '%s' with COHERE_API_KEY environment variable", model_id)
                model["api_key"] = new_api_key
                overridden = True
            model["enabled"] = True

        elif provider == "oci" and os.getenv("OCI_GENAI_SERVICE_ENDPOINT"):
            old_url = model.get("url", "")
            new_url = os.environ["OCI_GENAI_SERVICE_ENDPOINT"]
            if old_url != new_url:
                logger.info(
                    "Overriding 'url' for model '%s' with OCI_GENAI_SERVICE_ENDPOINT environment variable", model_id
                )
                model["url"] = new_url
                overridden = True
            model["enabled"] = True

        elif provider == "ollama" and os.getenv("ON_PREM_OLLAMA_URL"):
            old_url = model.get("url", "")
            new_url = os.environ["ON_PREM_OLLAMA_URL"]
            if old_url != new_url:
                logger.info("Overriding 'url' for model '%s' with ON_PREM_OLLAMA_URL environment variable", model_id)
                model["url"] = new_url
                overridden = True
            model["enabled"] = True

        elif provider == "huggingface" and os.getenv("ON_PREM_HF_URL"):
            old_url = model.get("url", "")
            new_url = os.environ["ON_PREM_HF_URL"]
            if old_url != new_url:
                logger.info("Overriding 'url' for model '%s' with ON_PREM_HF_URL environment variable", model_id)
                model["url"] = new_url
                overridden = True
            model["enabled"] = True

        if overridden:
            logger.debug("Model '%s' updated via environment variable overrides.", model_id)

    # Check URL accessible for enabled models and disable if not:
    url_access_cache = {}

    for model in models_list:
        url = model["url"]
        if model["enabled"]:
            if url not in url_access_cache:
                logger.debug("Testing %s URL: %s", model["id"], url)
                url_access_cache[url] = is_url_accessible(url)[0]
            else:
                logger.debug("Reusing cached result for %s for URL: %s", model["id"], url)

            model["enabled"] = url_access_cache[url]

    # Convert to Model objects
    model_objects = [Model(**model_dict) for model_dict in models_list]
    logger.info("Loaded %i Models.", len(model_objects))
    logger.debug("*** Bootstrapping Models - End")
    return model_objects


if __name__ == "__main__":
    main()
