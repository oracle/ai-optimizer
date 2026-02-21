"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Default model configurations bootstrapped on first startup.
"""
# spell-checker: ignore ollama pplx vllm huggingface mxbai nomic thenlper
# pylint: disable=inconsistent-quotes

# Environment variable -> (provider, field) mapping.
# apply_env_overrides() uses this to patch model_configs at startup so that
# freshly-set env vars always take effect, even when configs are restored from the DB.
ENV_OVERRIDES: list[tuple[str, str, str]] = [
    # (env_var,          provider,      field)
    ("COHERE_API_KEY", "cohere", "api_key"),
    ("OPENAI_API_KEY", "openai", "api_key"),
    ("PPLX_API_KEY", "perplexity", "api_key"),
    ("ON_PREM_OLLAMA_URL", "ollama", "api_base"),
    ("ON_PREM_HF_URL", "huggingface", "api_base"),
    ("ON_PREM_VLLM_URL", "hosted_vllm", "api_base"),
]

# fmt: off
DEFAULT_MODELS: list[dict] = [
    {
        'id': 'command-r',
        'enabled': False,
        'type': 'll',
        'provider': 'cohere',
        'api_key': '',
        'api_base': 'https://api.cohere.ai/compatibility/v1',
        'max_tokens': 4000,
        'max_input_tokens': 128000,
    },
    {
        'id': 'gpt-4o-mini',
        'enabled': False,
        'type': 'll',
        'provider': 'openai',
        'api_key': '',
        'api_base': 'https://api.openai.com/v1',
        'max_tokens': 16384,
        'max_input_tokens': 128000,
    },
    {
        'id': 'sonar',
        'enabled': False,
        'type': 'll',
        'provider': 'perplexity',
        'api_key': '',
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
        'enabled': False,
        'type': 'll',
        'provider': 'hosted_vllm',
        'api_key': '',
        'api_base': 'http://localhost:8000/v1',
        'max_tokens': 2048,
        'max_input_tokens': 16384,
    },
    {
        # This is intentionally last to line up with docs
        'id': 'llama3.1',
        'enabled': False,
        'type': 'll',
        'provider': 'ollama',
        'api_key': '',
        'api_base': 'http://127.0.0.1:11434',
        'max_tokens': 4096,
        'max_input_tokens': 131072,
    },
    {
        'id': 'thenlper/gte-base',
        'enabled': False,
        'type': 'embed',
        'provider': 'huggingface',
        'api_base': 'http://127.0.0.1:8080',
        'api_key': '',
        'max_chunk_size': 512,
    },
    {
        'id': 'text-embedding-3-small',
        'enabled': False,
        'type': 'embed',
        'provider': 'openai',
        'api_base': 'https://api.openai.com/v1',
        'api_key': '',
        'max_chunk_size': 1536,
    },
    {
        'id': 'embed-english-light-v3.0',
        'enabled': False,
        'type': 'embed',
        'provider': 'cohere',
        'api_base': 'https://api.cohere.ai/compatibility/v1',
        'api_key': '',
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
        # This is intentionally last to line up with docs
        'id': 'mxbai-embed-large',
        'enabled': False,
        'type': 'embed',
        'provider': 'ollama',
        'api_base': 'http://127.0.0.1:11434',
        'api_key': '',
        'max_chunk_size': 512,
    },
]
# fmt: on
