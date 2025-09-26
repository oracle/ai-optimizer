"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore ollama pplx huggingface genai giskard litellm ocigenai

from typing import Optional, Union
from urllib.parse import urlparse

import litellm

from langchain.embeddings import init_embeddings
from langchain_community.embeddings.oci_generative_ai import OCIGenAIEmbeddings
from langchain_core.embeddings.embeddings import Embeddings

import server.api.utils.oci as utils_oci
from server.bootstrap.bootstrap import MODEL_OBJECTS

from common.functions import is_url_accessible
from common import schema
from common import logging_config

logger = logging_config.logging.getLogger("api.utils.models")


#####################################################
# Exceptions
#####################################################
class URLUnreachableError(ValueError):
    """Raised when the submitted URL is unreachable."""


class InvalidModelError(ValueError):
    """Raised when the model data is invalid in some other way."""


class ExistsModelError(ValueError):
    """Raised when the model data already exist."""


class UnknownModelError(ValueError):
    """Raised when the model data doesn't exist."""


#####################################################
# CRUD Functions
#####################################################
def create(model: schema.Model, check_url: bool = True) -> schema.Model:
    """Create a new Model definition"""
    try:
        _ = get(model_id=model.id, model_provider=model.provider, model_type=model.type)
        raise ExistsModelError(f"Model: {model.provider}/{model.id} already exists.")
    except UnknownModelError:
        pass

    if check_url and model.api_base and not is_url_accessible(model.api_base)[0]:
        model.enabled = False

    MODEL_OBJECTS.append(model)
    return get(model_id=model.id, model_provider=model.provider, model_type=model.type)


def get(
    model_provider: Optional[schema.ModelProviderType] = None,
    model_id: Optional[schema.ModelIdType] = None,
    model_type: Optional[schema.ModelTypeType] = None,
    include_disabled: bool = True,
) -> Union[list[schema.Model], schema.Model, None]:
    """Used in direct call from list_models and agents.models"""
    logger.debug("%i models are defined", len(MODEL_OBJECTS))

    model_filtered = [
        model
        for model in MODEL_OBJECTS
        if (model_id is None or model.id == model_id)
        and (model_type is None or model.type == model_type)
        and (model_provider is None or model.provider == model_provider)
        and (include_disabled or model.enabled)
    ]
    logger.debug("%i models after filtering", len(model_filtered))

    if model_id and not model_filtered:
        raise UnknownModelError(f"{model_id} not found")
    if model_type and not model_filtered:
        raise UnknownModelError(f"{model_type} not found")

    if len(model_filtered) == 1:
        return model_filtered[0]

    return model_filtered


def update(payload: schema.Model) -> schema.Model:
    """Update an existing Model definition"""

    model_upd = get(model_provider=payload.provider, model_id=payload.id)
    if payload.enabled and not is_url_accessible(model_upd.api_base)[0]:
        model_upd.enabled = False
        raise URLUnreachableError("Model: Unable to update.  API URL is inaccessible.")

    for key, value in payload:
        if hasattr(model_upd, key):
            setattr(model_upd, key, value)
        else:
            raise InvalidModelError(f"Model: Invalid setting - {key}.")

    return model_upd


def delete(model_provider: schema.ModelProviderType, model_id: schema.ModelIdType) -> None:
    """Remove model from model objects"""
    MODEL_OBJECTS[:] = [m for m in MODEL_OBJECTS if (m.id, m.provider) != (model_id, model_provider)]


#####################################################
# Utility Functions
#####################################################
def get_supported_providers() -> list:
    """Return a list of supported Providers from LiteLLM"""
    return sorted([provider.value for provider in litellm.provider_list])


def create_genai(config: schema.OracleCloudSettings) -> list[schema.Model]:
    """Create and enable all GenAI models in the configured region"""
    region_models = utils_oci.get_genai_models(config, regional=True)
    if region_models:
        # Delete previously configured GenAI Models
        all_models = get()
        for model in all_models:
            if model.provider == "oci":
                delete(model_provider=model.provider, model_id=model.id)

    genai_models = []
    for model in region_models:
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
            genai_models.append(create(new_model, check_url=False))
        except ExistsModelError:
            logger.info("Model: %s already configured", new_model.id)

    return genai_models


def _get_full_config(model_config: dict, oci_config: schema.OracleCloudSettings = None) -> dict:
    logger.debug("Model Client: %s; OCI Config: %s", model_config, oci_config)
    model_provider, model_id = model_config["model"].split("/", 1)

    try:
        defined_model = get(
            model_provider=model_provider,
            model_id=model_id,
            include_disabled=False,
        ).model_dump()
    except UnknownModelError as ex:
        raise ex

    # Merge configurations, skipping None values
    full_model_config = {**defined_model, **{k: v for k, v in model_config.items() if v is not None}}
    provider = full_model_config.pop("provider")

    return full_model_config, provider


def get_litellm_config(
    model_config: dict, oci_config: schema.OracleCloudSettings = None, giskard: bool = False
) -> dict:
    """Establish LiteLLM client"""
    full_model_config, provider = _get_full_config(model_config, oci_config)

    # Get supported parameters and initialize config
    supported_params = litellm.get_supported_openai_params(model=model_config["model"])

    litellm_config = {
        k: full_model_config[k]
        for k in supported_params
        if k in full_model_config and full_model_config[k] is not None
    }
    if "cohere" in model_config["model"]:
        # Ensure we use the OpenAI compatible endpoint
        parsed = urlparse(full_model_config.get("api_base"))
        scheme = parsed.scheme or "https"
        netloc = "api.cohere.ai"
        # Always force the path
        path = "/compatibility/v1"
        full_model_config["api_base"] = f"{scheme}://{netloc}{path}"
    if "xai" in model_config["model"]:
        litellm_config.pop("presence_penalty", None)
        litellm_config.pop("frequency_penalty", None)

    litellm_config.update(
        {"model": model_config["model"], "api_base": full_model_config.get("api_base"), "drop_params": True}
    )
    if "api_key" in full_model_config:
        litellm_config["api_key"] = full_model_config["api_key"]

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

    if giskard:
        litellm_config.pop("model", None)
        litellm_config.pop("temperature", None)

    logger.debug("LiteLLM Config: %s", litellm_config)

    return litellm_config


def get_client_embed(model_config: dict, oci_config: schema.OracleCloudSettings) -> Embeddings:
    """Retrieve embedding model client"""
    full_model_config, provider = _get_full_config(model_config, oci_config)
    client = None

    if provider == "oci":
        client = OCIGenAIEmbeddings(
            model_id=full_model_config["id"],
            client=utils_oci.init_genai_client(oci_config),
            compartment_id=oci_config.genai_compartment_id,
        )
    else:
        if provider == "hosted_vllm":
            kwargs = {
                "provider": "openai",
                "model": full_model_config["id"],
                "base_url": full_model_config.get("api_base"),
                "check_embedding_ctx_length": False,  # To avoid Tiktoken pre-transform on not OpenAI provided server
            }
        else:
            kwargs = {
                "provider": provider,
                "model": full_model_config["id"],
                "base_url": full_model_config.get("api_base"),
            }

        if full_model_config.get("api_key"):  # only add if set
            kwargs["api_key"] = full_model_config["api_key"]
        client = init_embeddings(**kwargs)

    return client
