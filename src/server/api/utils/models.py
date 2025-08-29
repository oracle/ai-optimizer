"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore ollama pplx huggingface genai giskard litellm ocigenai

from urllib.parse import urlparse

from litellm import get_supported_openai_params
from openai import OpenAI

from langchain_core.language_models.chat_models import BaseChatModel
from langchain.chat_models import init_chat_model
from langchain.embeddings import init_embeddings

from langchain_community.chat_models.oci_generative_ai import ChatOCIGenAI
from langchain_community.embeddings.oci_generative_ai import OCIGenAIEmbeddings

from giskard.llm.client.openai import OpenAIClient

import server.api.utils.oci as util_oci
import server.api.core.models as core_models

from common.functions import is_url_accessible
import common.schema as schema
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("api.utils.models")


def update_model(model_id: schema.ModelIdType, payload: schema.Model) -> schema.Model:
    """Update an existing Model definition"""

    model_upd = core_models.get_model(model_id=model_id)
    if payload.enabled and not is_url_accessible(model_upd.api_base)[0]:
        model_upd.enabled = False
        raise core_models.URLUnreachableError("Model: Unable to update.  API URL is inaccessible.")

    for key, value in payload:
        if hasattr(model_upd, key):
            setattr(model_upd, key, value)
        else:
            raise core_models.InvalidModelError(f"Model: Invalid setting - {key}.")

    return model_upd


def create_genai_models(config: schema.OracleCloudSettings) -> list[schema.Model]:
    """Create and enable all GenAI models in the configured region"""
    region_models = util_oci.get_genai_models(config, regional=True)
    if region_models:
        # Delete previously configured GenAI Models
        all_models = core_models.get_model()
        for model in all_models:
            if model.provider == "oci":
                core_models.delete_model(model.id)

    genai_models = []
    for model in region_models:
        if model["vendor"] == "cohere":
            # Note that we can enable this if the GenAI endpoint supports OpenAI compat
            # https://docs.cohere.com/docs/compatibility-api
            logger.info("Skipping %s; no support for OCI GenAI cohere models", model["model_name"])
            continue
        model_dict = {}
        model_dict["provider"] = "oci"
        if "CHAT" in model["capabilities"]:
            model_dict["type"] = "ll"
            model_dict["context_length"] = 131072
        elif "TEXT_EMBEDDINGS" in model["capabilities"]:
            model_dict["type"] = "embed"
            model_dict["max_chunk_size"] = 8192
        else:
            continue

        model_dict["id"] = model["model_name"]
        model_dict["enabled"] = True
        model_dict["api_base"] = f"https://inference.generativeai.{config.genai_region}.oci.oraclecloud.com"
        # Create the Model
        try:
            new_model = schema.Model(**model_dict)
            genai_models.append(core_models.create_model(new_model, check_url=False))
        except core_models.ExistsModelError:
            logger.info("Model: %s already configured", new_model.id)

    return genai_models


def get_litellm_client(
    model_config: dict, oci_config: schema.OracleCloudSettings = None, giskard: bool = False
) -> dict:
    """Establish client"""
    logger.debug("Model Client: %s; OCI Config: %s; Giskard: %s", model_config, oci_config, giskard)

    try:
        defined_model = core_models.get_model(
            model_id=model_config["model"],
            include_disabled=False,
        ).model_dump()
    except core_models.UnknownModelError:
        return None

    # Merge configurations, skipping None values
    full_model_config = {**defined_model, **{k: v for k, v in model_config.items() if v is not None}}

    # Determine provider and model name
    provider = "openai" if full_model_config["provider"] == "openai_compatible" else full_model_config["provider"]
    model_name = f"{provider}/{full_model_config['id']}"

    # Get supported parameters and initialize config
    supported_params = get_supported_openai_params(model=model_name)
    litellm_config = {
        k: full_model_config[k]
        for k in supported_params
        if k in full_model_config and full_model_config[k] is not None
    }
    if "cohere" in model_name:
        # Ensure we use the OpenAI compatible endpoint
        parsed = urlparse(full_model_config.get("api_base"))
        scheme = parsed.scheme or "https"
        netloc = "api.cohere.ai"
        # Always force the path
        path = "/compatibility/v1"
        full_model_config["api_base"] = f"{scheme}://{netloc}{path}"

    litellm_config.update({"model": model_name, "api_base": full_model_config.get("api_base")})

    if provider == "oci":
        litellm_config.update(
            {
                "oci_user": oci_config.user,
                "oci_fingerprint": oci_config.fingerprint,
                "oci_tenancy": oci_config.tenancy,
                "oci_region": oci_config.genai_region,
                "oci_key_file": oci_config.key_file,
                "oci_compartment_id": oci_config.genai_compartment_id,
            }
        )

    return litellm_config
