"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for the exported LangChain MCP sample: optimizer_utils.config

The sample under ``src/client/source/langchain/rag`` is a standalone project that
ships to end users, so it is imported here the same way it runs: by adding its
own directory to ``sys.path`` and importing ``optimizer_utils.config`` directly.
"""
# spell-checker: disable

import pathlib
import sys
from unittest.mock import MagicMock, patch

import pytest

_RAG_DIR = pathlib.Path(__file__).resolve().parents[4] / "source" / "langchain" / "rag"
if str(_RAG_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_DIR))

from optimizer_utils import config  # noqa: E402  pylint: disable=wrong-import-position

pytestmark = pytest.mark.unit

MODULE = "optimizer_utils.config"


def _oci_data():
    """Settings payload as exported by /settings/export for an OCI GenAI config.

    ``client_settings.ll_model`` / ``vector_search`` carry ``provider`` + ``id``
    (the ``ModelIdentity`` shape the export endpoint actually writes), not a
    combined ``model`` key.
    """
    return {
        "model_configs": [
            {"id": "cohere.command-r", "provider": "oci", "api_base": "", "type": "ll"},
            {"id": "cohere.embed-english", "provider": "oci", "api_base": "", "type": "embed"},
        ],
        "oci_configs": [
            {
                "auth_profile": "DEFAULT",
                "authentication": "api_key",
                "tenancy": "ocid1.tenancy.oc1..tenancy",
                "user": "ocid1.user.oc1..user",
                "fingerprint": "aa:bb:cc:dd",
                "key_content": "-----BEGIN PRIVATE KEY-----\nABCDEF\n-----END PRIVATE KEY-----",
                "genai_compartment_id": "ocid1.compartment.oc1..compartment",
                "genai_region": "us-chicago-1",
            }
        ],
        "client_settings": {
            "oci": {"auth_profile": "DEFAULT"},
            "ll_model": {"provider": "oci", "id": "cohere.command-r"},
            "vector_search": {"provider": "oci", "id": "cohere.embed-english"},
        },
    }


def test_get_llm_reads_provider_id_from_export():
    """get_llm resolves from the exported provider/id fields (no 'model' key)."""
    llm = config.get_llm(_oci_data())
    assert llm.model == "oci/cohere.command-r"


def test_get_embeddings_reads_provider_id_from_export():
    """get_embeddings resolves from the exported provider/id fields."""
    emb = config.get_embeddings(_oci_data())
    assert emb.model_key == "oci/cohere.embed-english"


def test_get_llm_oci_forwards_auth_params():
    """An OCI language model carries the profile's auth params into LiteLLM."""
    model_kwargs = config.get_llm(_oci_data()).model_kwargs
    assert model_kwargs["oci_region"] == "us-chicago-1"
    assert model_kwargs["oci_compartment_id"] == "ocid1.compartment.oc1..compartment"
    assert model_kwargs["oci_tenancy"] == "ocid1.tenancy.oc1..tenancy"
    assert model_kwargs["oci_user"] == "ocid1.user.oc1..user"
    assert model_kwargs["oci_fingerprint"] == "aa:bb:cc:dd"
    assert model_kwargs["oci_key"].startswith("-----BEGIN PRIVATE KEY-----")


def test_get_embeddings_oci_forwards_auth_params():
    """An OCI embedding model carries the profile's auth params into litellm.embedding."""
    call_kwargs = config.get_embeddings(_oci_data())._call_kwargs()
    assert call_kwargs["model"] == "oci/cohere.embed-english"
    assert call_kwargs["oci_region"] == "us-chicago-1"
    assert call_kwargs["oci_compartment_id"] == "ocid1.compartment.oc1..compartment"
    assert call_kwargs["oci_tenancy"] == "ocid1.tenancy.oc1..tenancy"
    assert call_kwargs["oci_key"].startswith("-----BEGIN PRIVATE KEY-----")


def test_get_llm_openai_has_no_oci_params():
    """Non-OCI providers do not get OCI params injected."""
    data = {
        "model_configs": [
            {"id": "gpt-4o", "provider": "openai", "api_base": "https://api.openai.com", "api_key": "sk-x"}
        ],
        "client_settings": {"ll_model": {"provider": "openai", "id": "gpt-4o"}, "vector_search": {}},
    }
    llm = config.get_llm(data)
    assert llm.model == "openai/gpt-4o"
    assert not any(k.startswith("oci_") for k in llm.model_kwargs)


def test_get_vectorstore_table_name_matches_server_and_reads_username():
    """The table name derives from provider/id and DB auth reads 'username'.

    The table name must match the server's ``generate_vs_metadata`` formula
    (``{alias}_{provider}_{id}_{chunk}_{overlap}_{strategy}_{index}`` upper-cased
    with non-word chars collapsed) so the exported project queries the same
    table that ingestion created.
    """
    data = {
        "database_configs": [
            {"alias": "CORE", "username": "ADMIN", "password": "pw", "dsn": "//host:1521/svc"}
        ],
        "client_settings": {
            "database": {"alias": "CORE"},
            "vector_search": {
                "provider": "openai",
                "id": "text-embedding-3-small",
                "alias": "PRODUCT_DOCS",
                "chunk_size": 2000,
                "chunk_overlap": 200,
                "distance_strategy": "COSINE",
                "index_type": "HNSW",
            },
        },
    }

    with (
        patch(f"{MODULE}.oracledb.connect", return_value=MagicMock()),
        patch(f"{MODULE}.OracleVS") as mock_vs,
    ):
        config.get_vectorstore(data, MagicMock())

    table_name = mock_vs.call_args.kwargs["table_name"]
    assert table_name == "PRODUCT_DOCS_OPENAI_TEXT_EMBEDDING_3_SMALL_2000_200_COSINE_HNSW"
