"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

NOTE: Provide only one example per API to populate supported API lists; additional models should be
added via the APIs

WARNING: If you bootstrap additional Ollama Models, you will need to update the IaC to pull those.
         Large models will cause the IaC to take much longer to be available.
"""
# spell-checker:ignore configfile genai ollama pplx docos mxbai nomic thenlper
# spell-checker:ignore huggingface vllm

import os

from server.bootstrap.configfile import ConfigStore
from common.schema import Model
from common.functions import is_url_accessible
from common import logging_config

logger = logging_config.logging.getLogger("bootstrap.models")


def main() -> list[Model]:
    """Define example Model Support"""
    logger.debug("*** Bootstrapping Models - Start")

    def update_env_var(model: Model, provider: str, model_key: str, env_var: str):
        if model.get("provider") != provider:
            return

        new_value = os.environ.get(env_var)
        if not new_value:
            return

        old_value = model.get(model_key)
        if old_value != new_value:
            logger.debug("Overriding '%s' for model '%s' with %s environment variable", model_key, model.id, env_var)
            model[model_key] = new_value
            logger.debug("Model '%s' updated via environment variable overrides.", model.id)

    models_list = [
        {
            "id": "command-r",
            "enabled": os.getenv("COHERE_API_KEY") is not None,
            "type": "ll",
            "provider": "cohere",
            "api_key": os.environ.get("COHERE_API_KEY", default=""),
            "api_base": "https://api.cohere.ai/compatibility/v1",
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
            "api_base": "https://api.openai.com/v1",
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
            "api_base": "https://api.perplexity.ai",
            "context_length": 127072,
            "temperature": 0.2,
            "max_completion_tokens": 28000,
            "frequency_penalty": 1.0,
        },
        {
            "id": "phi-4",
            "enabled": False,
            "type": "ll",
            "provider": "huggingface",
            "api_key": "",
            "api_base": "http://localhost:1234/v1",
            "context_length": 131072,
            "temperature": 1.0,
            "max_completion_tokens": 4096,
            "frequency_penalty": 0.0,
        },
        # Commented out for IaC reasons (see WARNING above)
        # {
        #     "id": "gpt-oss:20b",
        #     "enabled": os.getenv("ON_PREM_OLLAMA_URL") is not None,
        #     "type": "ll",
        #     "provider": "ollama_chat",
        #     "api_key": "",
        #     "api_base": os.environ.get("ON_PREM_OLLAMA_URL", default="http://127.0.0.1:11434"),
        #     "context_length": 131072,
        #     "temperature": 1.0,
        #     "max_completion_tokens": 2048,
        #     "frequency_penalty": 0.0,
        # },
        {
            "id": "meta-llama/Llama-3.2-1B-Instruct",
            "enabled": os.getenv("ON_PREM_VLLM_URL") is not None,
            "type": "ll",
            "provider": "hosted_vllm",
            "api_key": "",
            "api_base": os.environ.get("ON_PREM_VLLM_URL", default="http://localhost:8000/v1"),
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
            "api_base": os.environ.get("ON_PREM_OLLAMA_URL", default="http://127.0.0.1:11434"),
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
            "api_base": os.environ.get("ON_PREM_HF_URL", default="http://127.0.0.1:8080"),
            "api_key": "",
            "max_chunk_size": 512,
        },
        {
            "id": "text-embedding-3-small",
            "enabled": os.getenv("OPENAI_API_KEY") is not None,
            "type": "embed",
            "provider": "openai",
            "api_base": "https://api.openai.com/v1",
            "api_key": os.environ.get("OPENAI_API_KEY", default=""),
            "max_chunk_size": 8191,
        },
        {
            "id": "embed-english-light-v3.0",
            "enabled": os.getenv("COHERE_API_KEY") is not None,
            "type": "embed",
            "provider": "cohere",
            "api_base": "https://api.cohere.ai/compatibility/v1",
            "api_key": os.environ.get("COHERE_API_KEY", default=""),
            "max_chunk_size": 512,
        },
        {
            "id": "nomic-ai/nomic-embed-text-v1",
            "enabled": False,
            "type": "embed",
            "provider": "hosted_vllm",
            "api_base": "http://localhost:8001/v1",
            "api_key": "",
            "max_chunk_size": 8192,
        },
        {
            # This is intentionally last to line up with docos
            "id": "mxbai-embed-large",
            "enabled": os.getenv("ON_PREM_OLLAMA_URL") is not None,
            "type": "embed",
            "provider": "ollama",
            "api_base": os.environ.get("ON_PREM_OLLAMA_URL", default="http://127.0.0.1:11434"),
            "api_key": "",
            "max_chunk_size": 8192,
        },
    ]

    # Check for duplicates
    unique_entries = set()
    for model in models_list:
        key = (model["provider"], model["id"])
        if key in unique_entries:
            raise ValueError(f"Model '{model['provider']}/{model['id']}' already exists.")
        unique_entries.add(key)

    # Merge with configuration if available
    configuration = ConfigStore.get()
    if configuration and configuration.model_configs:
        logger.debug("Merging model configs from ConfigStore")

        # Use (provider, id) tuple as key
        config_model_map = {(m.provider, m.id): m.model_dump() for m in configuration.model_configs}
        existing = {(m["provider"], m["id"]): m for m in models_list}

        def values_differ(a, b):
            if isinstance(a, bool) or isinstance(b, bool):
                return bool(a) != bool(b)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                return abs(a - b) > 1e-8
            if isinstance(a, str) and isinstance(b, str):
                return a.strip() != b.strip()
            return a != b

        for key, override in config_model_map.items():
            if key in existing:
                for k, v in override.items():
                    if k not in existing[key]:
                        continue
                    if values_differ(existing[key][k], v):
                        log_func = logger.debug if k == "api_key" else logger.info
                        log_func(
                            "Overriding field '%s' for model '%s/%s' (was: %r → now: %r)",
                            k,
                            key[0],  # provider
                            key[1],  # id
                            existing[key][k],
                            v,
                        )
                        existing[key][k] = v
            else:
                logger.info("Adding new model from ConfigStore: %s/%s", key[0], key[1])
                existing[key] = override

        models_list = list(existing.values())

    # Override with OS env vars (by API type)
    for model in models_list:
        update_env_var(model, "cohere", "api_key", "COHERE_API_KEY")
        update_env_var(model, "oci", "api_base", "OCI_GENAI_SERVICE_ENDPOINT")
        update_env_var(model, "ollama_chat", "api_base", "ON_PREM_OLLAMA_URL")
        update_env_var(model, "ollama", "api_base", "ON_PREM_OLLAMA_URL")
        update_env_var(model, "huggingface", "api_base", "ON_PREM_HF_URL")
        update_env_var(model, "meta-llama", "api_base", "ON_PREM_VLLM_URL")

    # Check URL accessible for enabled models and disable if not:
    url_access_cache = {}

    for model in models_list:
        url = model["api_base"]
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
