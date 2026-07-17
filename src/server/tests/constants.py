"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared constants for server tests.
"""

TEST_OPENAI_MODEL_ID = "gpt-5.4-mini"
TEST_OPENAI_MODEL_KEY = f"openai/{TEST_OPENAI_MODEL_ID}"
TEST_OPENAI_MODEL_API_KEY = f"{TEST_OPENAI_MODEL_KEY}.api_key"

# A differently-cased spelling of the model id, derived from the canonical
# value so case-insensitivity tests keep working when the constant changes.
TEST_OPENAI_MODEL_ID_MIXEDCASE = TEST_OPENAI_MODEL_ID.swapcase()

TEST_OPENAI_EMBED_ID = "text-embedding-3-small"
TEST_OPENAI_EMBED_KEY = f"openai/{TEST_OPENAI_EMBED_ID}"

TEST_OLLAMA_MODEL_ID = "granite4.1:8b"
TEST_OLLAMA_MODEL_KEY = f"ollama/{TEST_OLLAMA_MODEL_ID}"
# The key after LiteLLM normalizes an Ollama chat model (ollama -> ollama_chat).
TEST_OLLAMA_CHAT_KEY = f"ollama_chat/{TEST_OLLAMA_MODEL_ID}"

# Placeholder embedding-model key used by testbed/header tests where the
# embedding model is mocked and only its key string matters.
TEST_PLACEHOLDER_EMBED_KEY = "openai/embed"
