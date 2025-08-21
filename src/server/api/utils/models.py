"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore ollama pplx huggingface genai giskard litellm ocigenai

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
    if payload.enabled and not is_url_accessible(model_upd.url)[0]:
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
        model_dict["url"] = f"https://inference.generativeai.{config.genai_region}.oci.oraclecloud.com"
        # if model["vendor"] == "cohere":
        model_dict["openai_compat"] = False
        # Create the Model
        try:
            new_model = schema.Model(**model_dict)
            genai_models.append(core_models.create_model(new_model, check_url=False))
        except core_models.ExistsModelError:
            logger.info("Model: %s already configured", new_model.id)

    return genai_models


def get_client(model_config: dict, oci_config: schema.OracleCloudSettings, giskard: bool = False) -> BaseChatModel:
    """Retrieve model configuration"""
    logger.debug("Model Client: %s; OCI Config: %s; Giskard: %s", model_config, oci_config, giskard)
    try:
        defined_model = core_models.get_model(
            model_id=model_config["model"],
            include_disabled=False,
        ).model_dump()
    except core_models.UnknownModelError:
        return None

    full_model_config = {**defined_model, **{k: v for k, v in model_config.items() if v is not None}}
    client = None
    provider = full_model_config["provider"]
    if full_model_config["type"] == "ll" and not giskard:
        common_params = {
            k: full_model_config.get(k) for k in ["frequency_penalty", "presence_penalty", "top_p", "streaming"]
        }
        if provider != "oci":
            kwargs = {
                "model_provider": "openai" if provider == "openai_compatible" else provider,
                "model": full_model_config["id"],
                "base_url": full_model_config["url"],
                "temperature": full_model_config["temperature"],
                "max_tokens": full_model_config["max_completion_tokens"],
                **common_params,
            }
            # Only add the api_key if it is set
            if full_model_config.get("api_key"):
                kwargs["api_key"] = full_model_config["api_key"]

            client = init_chat_model(**kwargs)
        else:
            client = ChatOCIGenAI(
                model_id=full_model_config["id"],
                client=util_oci.init_genai_client(oci_config),
                compartment_id=oci_config.genai_compartment_id,
                model_kwargs={
                    (k if k != "max_completion_tokens" else "max_tokens"): v
                    for k, v in common_params.items()
                    if k not in {"streaming"}
                },
            )

    if full_model_config["type"] == "embed" and not giskard:
        if provider != "oci":
            kwargs = {
                "provider": "openai" if provider == "openai_compatible" else provider,
                "model": full_model_config["id"],
                "base_url": full_model_config["url"],
            }
            # Only add the api_key if it is set
            if full_model_config.get("api_key"):
                kwargs["api_key"] = full_model_config["api_key"]

            client = init_embeddings(**kwargs)
        else:
            client = OCIGenAIEmbeddings(
                model_id=full_model_config["id"],
                client=util_oci.init_genai_client(oci_config),
                compartment_id=oci_config.genai_compartment_id,
            )

    if giskard:
        logger.debug("Creating Giskard Client")
        giskard_key = full_model_config["api_key"] or "giskard"
        _client = OpenAI(api_key=giskard_key, base_url=full_model_config["url"])
        client = OpenAIClient(model=full_model_config["id"], client=_client)

    logger.debug("Configured Client: %s", vars(client))
    return client
