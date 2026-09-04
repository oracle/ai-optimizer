"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared constants for server tests.
"""

from typing import Any

TEST_DB_DSN = "//localhost:1525/FREEPDB1"

# Payloads use the field names accepted by the corresponding application
# interfaces.  Keeping the values and their fields together makes test data
# reusable without scattering credential-shaped constants through test files.
test_auth: dict[str, dict[str, Any]] = {
    "generic": {
        "username": "testuser",
        "password": "secret",
        "wallet_password": "wallet_secret",
    },
    "short": {"username": "u", "password": "p"},
    "simple": {"username": "test", "password": "test"},
    "oracle": {"username": "PYTEST", "password": "OrA_41_3xPl0d3r"},
    "oracle_wrong": {"password": "WRONG_PASSWORD_123"},
    "oidc_admin": {"username": "admin@example.test", "password": "admin-password"},
    "oidc_client": {"web_client_secret": "web-client-secret"},
    "oidc_bootstrap": {"password": "generated-password"},
    "oidc_alternate": {
        "username": "carol@example.test",
        "email": "carol@example.test",
        "password": "carol-password",
    },
    "oidc_old": {"password": "old-generated-password"},
    "oidc_durable": {"password": "durable-launcher-password"},
    "oidc_wrong": {"password": "wrong-password"},
    "oidc_wrong_client": {"client_secret": "wrong-secret"},
    "api": {"api_key": "test-key"},
    "model": {"api_key": "sk-secret-key"},
    "embed_model": {"api_key": "sk-embed-key"},
    "pull_model": {"api_key": "sk-secret"},
    "generic_model": {"api_key": "sk-test"},
    "masked_model": {"api_key": "sk-secret"},
    "database_owner": {"username": "OWNER", "password": "pw"},
    "database_end_user": {"username": "SCOUT1"},
    "database_alt_owner": {"username": "owner"},
    "database_alt": {"username": "produser", "password": "prod_secret"},
    "database_core": {"username": "coreuser", "password": "core_secret"},
    "database_probe": {"password": "DBPASS"},
    "database_invalid": {"username": "BADUSER", "password": "badpw"},
    "database_new": {"password": "new_password"},
    "database_collision": {"username": "SOMEONE"},
    "embed": {"username": "user", "password": "testpass"},
    "embed_submit": {"username": "user_at_submit", "password": "password_at_submit"},
    "embed_rotated": {"username": "user_after_rotation", "password": "password_after_rotation"},
    "settings_database": {"db_username": "optimizer", "db_password": "database-password"},
    "retired_client": {"password": "retired-password"},
    "sqlcl": {"username": "scott", "password": "tiger"},
    "sqlcl_special": {"username": 'user"name', "password": "pa@ss/word"},
    "hunter": {"password": "hunter2"},
    "wallet": {"password": "walletpw"},
}
test_auth["deepsec_end_user"] = {"end_user": test_auth["database_end_user"]["username"]}
test_auth["embed_owner"] = {
    "username": test_auth["embed"]["username"],
    "password": test_auth["database_owner"]["password"],
}
test_auth["render"] = {
    "password": test_auth["hunter"]["password"],
    "wallet_password": test_auth["wallet"]["password"],
}

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
