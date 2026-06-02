"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

import logging
import os
import re
from typing import Any, Optional

import litellm
import oracledb
from langchain_core.embeddings import Embeddings
from langchain_litellm import ChatLiteLLM
from langchain_oracledb.vectorstores.oraclevs import DistanceStrategy, OracleVS

LOGGER = logging.getLogger(__name__)


class LiteLLMEmbeddings(Embeddings):
    """LangChain ``Embeddings`` backed by ``litellm.embedding``.

    Routes every provider through LiteLLM so the same model string syntax
    (``provider/model``) used for the chat model also drives embeddings,
    mirroring the core AI Optimizer runtime.
    """

    def __init__(
        self,
        model_key: str,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        extra_params: Optional[dict[str, Any]] = None,
    ) -> None:
        self.model_key = model_key
        self.api_key = api_key
        self.api_base = api_base
        self.extra_params = extra_params or {}

    def _call_kwargs(self) -> dict[str, Any]:
        # extra_params first so explicit model/api_key/api_base cannot be shadowed.
        kwargs: dict[str, Any] = {**self.extra_params, "model": self.model_key}
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        return kwargs

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        resp = litellm.embedding(input=texts, **self._call_kwargs())
        return [item["embedding"] for item in resp.data]

    def embed_query(self, text: str) -> list[float]:
        resp = litellm.embedding(input=[text], **self._call_kwargs())
        return resp.data[0]["embedding"]


# OCI custom-trained endpoints are addressed by OCID rather than model name and
# require DEDICATED serving mode (matches the core AI Optimizer runtime).
_OCI_CUSTOM_ENDPOINT_PREFIX = "ocid1.generativeaiendpoint"


def _oci_signer(profile):
    """Build an OCI signer for principal / security-token auth profiles, else None.

    The ``oci`` SDK is imported lazily so it is only required when an OCI
    signer-based profile is actually used by the exported configuration.
    """
    auth = profile.get("authentication")
    if auth not in ("instance_principal", "resource_principal", "oke_workload_identity", "security_token"):
        return None

    import oci  # pylint: disable=import-outside-toplevel,import-error

    if auth == "instance_principal":
        return oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
    if auth == "resource_principal":
        return oci.auth.signers.get_resource_principals_signer()
    if auth == "oke_workload_identity":
        return oci.auth.signers.get_oke_workload_identity_resource_principal_signer()
    # security_token
    if not profile.get("security_token_file"):
        raise ValueError(f"security_token profile '{profile.get('auth_profile')}' has no security_token_file")
    with open(profile["security_token_file"], "r", encoding="utf-8") as token_file:
        token = token_file.read().strip()
    passphrase = profile.get("pass_phrase")
    if profile.get("key_file"):
        private_key = oci.signer.load_private_key_from_file(profile["key_file"], passphrase)
    elif profile.get("key_content"):
        private_key = oci.signer.load_private_key(profile["key_content"], passphrase)
    else:
        raise ValueError(f"security_token profile '{profile.get('auth_profile')}' has no key configured")
    return oci.auth.signers.SecurityTokenSigner(token, private_key)


def _oci_params(data, model):
    """Build LiteLLM OCI auth params from the OCI profile selected in the settings.

    Mirrors the core AI Optimizer so an exported OCI GenAI configuration
    authenticates the same way: region and compartment plus either a signer
    (principal / security-token auth) or API-key fields.
    """
    profile_name = data["client_settings"].get("oci", {}).get("auth_profile")
    profiles_by_name = {p.get("auth_profile"): p for p in data.get("oci_configs", [])}
    profile = profiles_by_name.get(profile_name)
    if profile is None:
        raise ValueError(f"OCI profile '{profile_name}' not found in oci_configs")

    params: dict[str, Any] = {
        "oci_region": profile.get("genai_region"),
        "oci_compartment_id": profile.get("genai_compartment_id"),
    }
    signer = _oci_signer(profile)
    if signer is not None:
        params["oci_signer"] = signer
    else:
        params["oci_tenancy"] = profile.get("tenancy")
        params["oci_user"] = profile.get("user")
        params["oci_fingerprint"] = profile.get("fingerprint")
        if profile.get("key_content"):
            params["oci_key"] = profile["key_content"]
        elif profile.get("key_file"):
            params["oci_key_file"] = profile["key_file"]

    # Custom-trained endpoints are addressed by OCID via DEDICATED serving mode.
    if model.startswith(_OCI_CUSTOM_ENDPOINT_PREFIX):
        params["oci_serving_mode"] = "DEDICATED"
        params["oci_endpoint_id"] = model
    return params


def _resolve_model(data, model_settings):
    """Resolve a client-settings model selection to LiteLLM connection params.

    Args:
        data: Configuration dictionary containing ``model_configs``
        model_settings: The ``ll_model`` / ``vector_search`` settings block,
            carrying the ``id`` (and ``provider``) the export endpoint writes.

    Returns:
        A ``(model_key, api_base, api_key, extra_params)`` tuple, where
        ``model_key`` is the ``provider/model`` string LiteLLM routes on,
        ``api_key`` is ``None`` when unset so LiteLLM's own credential
        resolution is not overridden, and ``extra_params`` carries provider
        specific kwargs (OCI auth params for the ``oci`` provider).
    """
    model = model_settings["id"]
    models_by_id = {m["id"]: m for m in data.get("model_configs", [])}
    model_config = models_by_id.get(model)
    if model_config is None:
        raise ValueError(f"Model '{model}' not found in model_configs")
    provider = model_config["provider"]
    model_key = f"{provider}/{model}"
    api_base = model_config["api_base"]
    api_key = model_config.get("api_key") or None
    extra_params = _oci_params(data, model) if provider == "oci" else {}
    LOGGER.info("resolved model_key=%s api_base=%s", model_key, api_base)
    return model_key, api_base, api_key, extra_params


def get_llm(data):
    """
    Get LLM instance based on configuration data.

    Args:
        data: Configuration dictionary containing model settings

    Returns:
        Configured LLM instance
    """
    model_key, api_base, api_key, extra_params = _resolve_model(data, data["client_settings"]["ll_model"])
    return ChatLiteLLM(model=model_key, api_key=api_key, api_base=api_base, model_kwargs=extra_params)


def get_embeddings(data):
    """
    Get embeddings instance based on configuration data.

    Args:
        data: Configuration dictionary containing embedding model settings

    Returns:
        Configured embeddings instance
    """
    model_key, api_base, api_key, extra_params = _resolve_model(data, data["client_settings"]["vector_search"])
    return LiteLLMEmbeddings(model_key=model_key, api_key=api_key, api_base=api_base, extra_params=extra_params)


def get_vectorstore(data, embeddings):
    """
    Get vector store instance based on configuration data.

    Args:
        data: Configuration dictionary containing database and vector search settings
        embeddings: Embeddings instance to use for the vector store

    Returns:
        Configured OracleVS vector store instance
    """
    db_alias = data["client_settings"]["database"]["alias"]

    db_by_name = {m["alias"]: m for m in data.get("database_configs", [])}
    db_config = db_by_name.get(db_alias)
    if db_config is None:
        raise ValueError(f"Database '{db_alias}' not found in database_configs")

    vector_search = data["client_settings"]["vector_search"]
    table_alias = vector_search["alias"]
    # The exported settings carry provider + id; recombine them into the same
    # token the server uses for the table name so we target the table that
    # ingestion created (``re.sub`` below collapses the slash to an underscore).
    model = f"{vector_search['provider']}/{vector_search['id']}"
    chunk_size = str(data["client_settings"]["vector_search"]["chunk_size"])
    chunk_overlap = str(data["client_settings"]["vector_search"]["chunk_overlap"])
    distance_metric = data["client_settings"]["vector_search"]["distance_strategy"]
    index_type = data["client_settings"]["vector_search"]["index_type"]

    table_string = f"{table_alias}_{model}_{chunk_size}_{chunk_overlap}_{distance_metric}_{index_type}"
    db_table = re.sub(r"\W", "_", table_string.upper())
    LOGGER.info("db_table:%s", db_table)

    user = db_config["username"]
    password = db_config.get("password") or os.environ.get("DB_PASSWORD", "")
    dsn = db_config["dsn"]

    # ADB connection with wallet
    wallet_pwd = db_config.get("wallet_password") or os.environ.get("DB_WALLET_PASSWORD", "")
    wallet_location = db_config.get("wallet_location")

    LOGGER.info("%s: %s - %s", db_table, user, dsn)

    if wallet_pwd and wallet_location:
        LOGGER.info("ADB connection starting..")
        conn23c = oracledb.connect(
            user=user, password=password, dsn=dsn, wallet_location=wallet_location, wallet_password=wallet_pwd
        )
    else:
        conn23c = oracledb.connect(user=user, password=password, dsn=dsn)

    LOGGER.info("DB Connection successful!")
    metric = data["client_settings"]["vector_search"]["distance_strategy"]

    dist_strategy = DistanceStrategy.COSINE
    if metric == "COSINE":
        dist_strategy = DistanceStrategy.COSINE
    elif metric == "EUCLIDEAN":
        dist_strategy = DistanceStrategy.EUCLIDEAN_DISTANCE
    elif metric == "DOT_PRODUCT":
        dist_strategy = DistanceStrategy.DOT_PRODUCT

    LOGGER.info(embeddings)
    knowledge_base = OracleVS(
        client=conn23c, table_name=db_table, embedding_function=embeddings, distance_strategy=dist_strategy
    )

    return knowledge_base
