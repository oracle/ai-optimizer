"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore ollama pplx huggingface genai giskard litellm

from openai import OpenAI

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_cohere import ChatCohere, CohereEmbeddings
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_huggingface import HuggingFaceEndpointEmbeddings
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
            if any(x in model.api for x in ("ChatOCIGenAI", "OCIGenAIEmbeddings")):
                core_models.delete_model(model.id)

    genai_models = []
    for model in region_models:
        model_dict = {}
        if "CHAT" in model["capabilities"]:
            model_dict["type"] = "ll"
            model_dict["api"] = "ChatOCIGenAI"
            model_dict["context_length"] = 131072
        elif "TEXT_EMBEDDINGS" in model["capabilities"]:
            model_dict["type"] = "embed"
            model_dict["api"] = "OCIGenAIEmbeddings"
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

    def get_key_value(
        models: list[schema.ModelAccess],
        model_id: schema.ModelIdType,
        model_key: str,
    ) -> str:
        """Return a models key value of its configuration"""
        for model in models:
            if model.id == model_id:
                return getattr(model, model_key, None)
        return None

    logger.debug("Model Config: %s; OCI Config: %s; Giskard: %s", model_config, oci_config, giskard)
    all_models = core_models.get_model()

    model_id = model_config["model"]
    model_api = get_key_value(all_models, model_id, "api")
    model_api_key = get_key_value(all_models, model_id, "api_key")
    model_url = get_key_value(all_models, model_id, "url")

    # Determine if configuring an embedding model
    try:
        embedding = model_config["enabled"]
    except (AttributeError, KeyError):
        embedding = False

    # schema.Model Classes
    model_classes = {}
    if not embedding:
        logger.debug("Configuring LL Model")
        ll_common_params = {}
        for key in [
            "temperature",
            "top_p",
            "frequency_penalty",
            "presence_penalty",
            "max_completion_tokens",
            "streaming",
        ]:
            try:
                logger.debug("--> Setting: %s; was sent %s", key, model_config[key])
                ll_common_params[key] = model_config[key] or get_key_value(all_models, model_id, key)
            except KeyError:
                # Mainly for embeddings
                continue
        logger.debug("LL Model Parameters: %s", ll_common_params)
        model_classes = {
            "OpenAI": lambda: ChatOpenAI(model=model_id, api_key=model_api_key, **ll_common_params),
            "CompatOpenAI": lambda: ChatOpenAI(
                model=model_id, base_url=model_url, api_key=model_api_key or "api_compat", **ll_common_params
            ),
            "Cohere": lambda: ChatCohere(model=model_id, cohere_api_key=model_api_key, **ll_common_params),
            "ChatOllama": lambda: ChatOllama(
                model=model_id,
                base_url=model_url,
                **ll_common_params,
                num_predict=ll_common_params["max_completion_tokens"],
            ),
            "Perplexity": lambda: ChatOpenAI(
                model=model_id, base_url=model_url, api_key=model_api_key, **ll_common_params
            ),
            "ChatOCIGenAI": lambda oci_cfg=oci_config: ChatOCIGenAI(
                model_id=model_id,
                client=util_oci.init_genai_client(oci_cfg),
                compartment_id=oci_cfg.genai_compartment_id,
                model_kwargs={
                    (k if k != "max_completion_tokens" else "max_tokens"): v
                    for k, v in ll_common_params.items()
                    if k not in {"streaming"}
                },
            ),
        }
    if embedding:
        logger.debug("Configuring Embed Model")
        model_classes = {
            "OpenAIEmbeddings": lambda: OpenAIEmbeddings(model=model_id, api_key=model_api_key),
            "CompatOpenAIEmbeddings": lambda: OpenAIEmbeddings(
                model=model_id,
                base_url=model_url,
                api_key=model_api_key or "api_compat",
                check_embedding_ctx_length=False,
            ),
            "CohereEmbeddings": lambda: CohereEmbeddings(model=model_id, cohere_api_key=model_api_key),
            "OllamaEmbeddings": lambda: OllamaEmbeddings(model=model_id, base_url=model_url),
            "HuggingFaceEndpointEmbeddings": lambda: HuggingFaceEndpointEmbeddings(model=model_url),
            "OCIGenAIEmbeddings": lambda oci_cfg=oci_config: OCIGenAIEmbeddings(
                model_id=model_id,
                client=util_oci.init_genai_client(oci_cfg),
                compartment=oci_cfg.compartment,
            ),
        }

    try:
        if giskard:
            logger.debug("Creating Giskard Client for %s in %s", model_api, model_classes)
            giskard_key = model_api_key or "giskard"
            if giskard_key == "giskard" and model_api == "CompatOpenAI":
                _client = OpenAI(api_key=giskard_key, base_url=f"{model_url}")
            else:
                _client = OpenAI(api_key=giskard_key, base_url=f"{model_url}/v1")
            client = OpenAIClient(model=model_id, client=_client)
        else:
            logger.debug("Searching for %s in %s", model_api, model_classes)
            client = model_classes[model_api]()
            logger.debug("Model Client: %s", client)
        return client
    except (UnboundLocalError, KeyError):
        logger.error("Unable to find client; expect trouble!")
        return None
