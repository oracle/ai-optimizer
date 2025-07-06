"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

NOTE: Provide only one example per API to populate supported API lists; additional models should be
added via the APIs
"""
# spell-checker:ignore ollama, minilm, pplx, thenlper, mxbai, nomic, genai, docos

import os
from common.schema import Model
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("server.bootstrap.model_def")


def main() -> list[Model]:
    """Define example Model Support"""
    models_list = [
        {
            "name": "command-r",
            "enabled": os.getenv("COHERE_API_KEY") is not None,
            "type": "ll",
            "api": "Cohere",
            "api_key": os.environ.get("COHERE_API_KEY", default=""),
            "openai_compat": False,
            "url": "https://api.cohere.ai",
            "context_length": 127072,
            "temperature": 0.3,
            "max_completion_tokens": 4096,
            "frequency_penalty": 0.0,
        },
        {
            "name": "gpt-4o-mini",
            "enabled": os.getenv("OPENAI_API_KEY") is not None,
            "type": "ll",
            "api": "OpenAI",
            "api_key": os.environ.get("OPENAI_API_KEY", default=""),
            "openai_compat": True,
            "url": "https://api.openai.com",
            "context_length": 127072,
            "temperature": 1.0,
            "max_completion_tokens": 4096,
            "frequency_penalty": 0.0,
        },
        {
            "name": "sonar",
            "enabled": os.getenv("PPLX_API_KEY") is not None,
            "type": "ll",
            "api": "Perplexity",
            "api_key": os.environ.get("PPLX_API_KEY", default=""),
            "openai_compat": True,
            "url": "https://api.perplexity.ai",
            "context_length": 127072,
            "temperature": 0.2,
            "max_completion_tokens": 28000,
            "frequency_penalty": 1.0,
        },
        {
            "name": "phi-4",
            "enabled": False,
            "type": "ll",
            "api": "CompatOpenAI",
            "api_key": "",
            "openai_compat": True,
            "url": "http://localhost:1234/v1",
            "context_length": 131072,
            "temperature": 1.0,
            "max_completion_tokens": 4096,
            "frequency_penalty": 0.0,
        },
        {
            # OCI GenAI; url and enabled will be determined by OCI config
            "name": "cohere.command-r-plus-08-2024",
            "enabled": os.getenv("OCI_GENAI_COMPARTMENT_ID") is not None
            and os.getenv("OCI_GENAI_SERVICE_ENDPOINT") is not None,
            "type": "ll",
            "api": "ChatOCIGenAI",
            "url": os.environ.get("OCI_GENAI_SERVICE_ENDPOINT", None),
            "api_key": "",
            "openai_compat": False,
            "context_length": 131072,
            "temperature": 0.3,
            "max_completion_tokens": 4000,
            "frequency_penalty": 0.0,
        },
        {
            # This is intentionally last to line up with docos
            "name": "llama3.1",
            "enabled": os.getenv("ON_PREM_OLLAMA_URL") is not None,
            "type": "ll",
            "api": "ChatOllama",
            "api_key": "",
            "openai_compat": True,
            "url": os.environ.get("ON_PREM_OLLAMA_URL", default="http://127.0.0.1:11434"),
            "context_length": 131072,
            "temperature": 1.0,
            "max_completion_tokens": 2048,
            "frequency_penalty": 0.0,
        },
        {
            "name": "thenlper/gte-base",
            "enabled": os.getenv("ON_PREM_HF_URL") is not None,
            "type": "embed",
            "api": "HuggingFaceEndpointEmbeddings",
            "url": os.environ.get("ON_PREM_HF_URL", default="http://127.0.0.1:8080"),
            "api_key": "",
            "openai_compat": True,
            "max_chunk_size": 512,
        },
        {
            "name": "text-embedding-3-small",
            "enabled": os.getenv("OPENAI_API_KEY") is not None,
            "type": "embed",
            "api": "OpenAIEmbeddings",
            "url": "https://api.openai.com",
            "api_key": os.environ.get("OPENAI_API_KEY", default=""),
            "openai_compat": True,
            "max_chunk_size": 8191,
        },
        {
            "name": "embed-english-light-v3.0",
            "enabled": os.getenv("COHERE_API_KEY") is not None,
            "type": "embed",
            "api": "CohereEmbeddings",
            "url": "https://api.cohere.ai",
            "api_key": os.environ.get("COHERE_API_KEY", default=""),
            "openai_compat": False,
            "max_chunk_size": 512,
        },
        {
            # OCI GenAI; url and enabled will be determined by OCI config
            "name": "cohere.embed-multilingual-v3.0",
            "enabled": os.getenv("OCI_GENAI_COMPARTMENT_ID") is not None
            and os.getenv("OCI_GENAI_SERVICE_ENDPOINT") is not None,
            "type": "embed",
            "api": "OCIGenAIEmbeddings",
            "url": os.environ.get("OCI_GENAI_SERVICE_ENDPOINT", None),
            "api_key": "",
            "openai_compat": False,
            "max_chunk_size": 4096,
        },
        {
            "name": "text-embedding-nomic-embed-text-v1.5",
            "enabled": False,
            "type": "embed",
            "api": "CompatOpenAIEmbeddings",
            "url": "http://localhost:1234/v1",
            "api_key": "",
            "openai_compat": True,
            "max_chunk_size": 8192,
        },
        {
            # This is intentionally last to line up with docos
            "name": "mxbai-embed-large",
            "enabled": os.getenv("ON_PREM_OLLAMA_URL") is not None,
            "type": "embed",
            "api": "OllamaEmbeddings",
            "url": os.environ.get("ON_PREM_OLLAMA_URL", default="http://127.0.0.1:11434"),
            "api_key": "",
            "openai_compat": True,
            "max_chunk_size": 512,
        },
    ]

    # Check for Duplicates
    unique_entries = set()
    for model in models_list:
        if model["name"] in unique_entries:
            raise ValueError(f"Model '{model['name']}': already exists.")
        unique_entries.add(model["name"])
    model_objects = [Model(**model_dict) for model_dict in models_list]
    return model_objects


if __name__ == "__main__":
    main()
