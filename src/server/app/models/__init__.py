"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

AI model registry and startup lifecycle.
"""

import logging
import os

from .schemas import ModelConfig

LOGGER = logging.getLogger(__name__)

# fmt: off
_DEFAULT_MODELS: list[dict] = [
    {
        'id': 'command-r',
        'enabled': os.getenv('COHERE_API_KEY') is not None,
        'type': 'll',
        'provider': 'cohere',
        'api_key': os.environ.get('COHERE_API_KEY', default=''),
        'api_base': 'https://api.cohere.ai/compatibility/v1',
        'max_tokens': 4000,
        'max_input_tokens': 128000,
    },
    {
        'id': 'gpt-4o-mini',
        'enabled': os.getenv('OPENAI_API_KEY') is not None,
        'type': 'll',
        'provider': 'openai',
        'api_key': os.environ.get('OPENAI_API_KEY', default=''),
        'api_base': 'https://api.openai.com/v1',
        'max_tokens': 16384,
        'max_input_tokens': 128000,
    },
    {
        'id': 'sonar',
        'enabled': os.getenv('PPLX_API_KEY') is not None,
        'type': 'll',
        'provider': 'perplexity',
        'api_key': os.environ.get('PPLX_API_KEY', default=''),
        'api_base': 'https://api.perplexity.ai',
        'max_tokens': 8000,
        'max_input_tokens': 128000,
    },
    {
        'id': 'phi-4',
        'enabled': False,
        'type': 'll',
        'provider': 'huggingface',
        'api_key': '',
        'api_base': 'http://localhost:1234/v1',
        'max_input_tokens': 16384,
    },
    {
        'id': 'meta-llama/Llama-3.2-1B-Instruct',
        'enabled': os.getenv('ON_PREM_VLLM_URL') is not None,
        'type': 'll',
        'provider': 'hosted_vllm',
        'api_key': '',
        'api_base': os.environ.get('ON_PREM_VLLM_URL', default='http://localhost:8000/v1'),
        'max_tokens': 2048,
        'max_input_tokens': 16384,
    },
    {
        # This is intentionally last to line up with docos
        'id': 'llama3.1',
        'enabled': os.getenv('ON_PREM_OLLAMA_URL') is not None,
        'type': 'll',
        'provider': 'ollama',
        'api_key': '',
        'api_base': os.environ.get('ON_PREM_OLLAMA_URL', default='http://127.0.0.1:11434'),
        'max_tokens': 4096,
        'max_input_tokens': 131072,
    },
    {
        'id': 'thenlper/gte-base',
        'enabled': os.getenv('ON_PREM_HF_URL') is not None,
        'type': 'embed',
        'provider': 'huggingface',
        'api_base': os.environ.get('ON_PREM_HF_URL', default='http://127.0.0.1:8080'),
        'api_key': '',
        'max_chunk_size': 512,
    },
    {
        'id': 'text-embedding-3-small',
        'enabled': os.getenv('OPENAI_API_KEY') is not None,
        'type': 'embed',
        'provider': 'openai',
        'api_base': 'https://api.openai.com/v1',
        'api_key': os.environ.get('OPENAI_API_KEY', default=''),
        'max_chunk_size': 1536,
    },
    {
        'id': 'embed-english-light-v3.0',
        'enabled': os.getenv('COHERE_API_KEY') is not None,
        'type': 'embed',
        'provider': 'cohere',
        'api_base': 'https://api.cohere.ai/compatibility/v1',
        'api_key': os.environ.get('COHERE_API_KEY', default=''),
        'max_chunk_size': 512,
    },
    {
        'id': 'nomic-ai/nomic-embed-text-v1',
        'enabled': False,
        'type': 'embed',
        'provider': 'hosted_vllm',
        'api_base': 'http://localhost:8001/v1',
        'api_key': '',
        'max_chunk_size': 8192,
    },
    {
        # This is intentionally last to line up with docos
        'id': 'mxbai-embed-large',
        'enabled': os.getenv('ON_PREM_OLLAMA_URL') is not None,
        'type': 'embed',
        'provider': 'ollama',
        'api_base': os.environ.get('ON_PREM_OLLAMA_URL', default='http://127.0.0.1:11434'),
        'api_key': '',
        'max_chunk_size': 512,
    },
]
# fmt: on


def _model_key(model_id: str, provider: str) -> tuple[str, str]:
    """Return the composite unique key for a model config."""
    return (model_id.casefold(), provider.casefold())


def register_model(model: ModelConfig) -> None:
    """Append *model* to settings.model_configs (deduplicate by (id, provider), last-write wins)."""
    from server.app.core.settings import settings  # pylint: disable=import-outside-toplevel

    key = _model_key(model.id, model.provider)
    settings.model_configs = [
        m for m in settings.model_configs if _model_key(m.id, m.provider) != key
    ] + [model]


async def load_default_models() -> None:
    """Startup entry point: populate model_configs with built-in defaults."""
    from server.app.core.settings import settings  # pylint: disable=import-outside-toplevel

    if settings.model_configs:
        LOGGER.info('Model configs already populated (%d), skipping defaults', len(settings.model_configs))
        return

    for entry in _DEFAULT_MODELS:
        register_model(ModelConfig(**entry))

    LOGGER.info('Loaded %d default model config(s)', len(settings.model_configs))
