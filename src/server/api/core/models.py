"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore ollama, pplx, huggingface, genai, giskard

from typing import Optional, Union

from openai import OpenAI

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_cohere import ChatCohere, CohereEmbeddings
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_huggingface import HuggingFaceEndpointEmbeddings
from langchain_community.chat_models.oci_generative_ai import ChatOCIGenAI
from langchain_community.embeddings.oci_generative_ai import OCIGenAIEmbeddings

from giskard.llm.client.openai import OpenAIClient

from server.api.core import bootstrap
from server.api.utils import oci
import common.schema as schema
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("api.core.models")


#####################################################
# Functions
#####################################################
def get_model(
    model_id: Optional[schema.ModelIdType] = None,
    model_type: Optional[schema.ModelTypeType] = None,
    include_disabled: bool = True,
) -> Union[list[schema.Model], schema.Model, None]:
    """Used in direct call from list_models and agents.models"""
    model_objects = bootstrap.MODEL_OBJECTS

    logger.debug("%i models are defined", len(model_objects))

    model_filtered = [
        model
        for model in model_objects
        if (model_id is None or model.id == model_id)
        and (model_type is None or model.type == model_type)
        and (include_disabled or model.enabled)
    ]
    logger.debug("%i models after filtering", len(model_filtered))

    if model_id and not model_filtered:
        raise ValueError(f"{model_id} not found")
    if model_type and not model_filtered:
        raise ValueError(f"{model_type} not found")

    if len(model_filtered) == 1:
        return model_filtered[0]

    return model_filtered


def create_model(model: schema.Model) -> schema.Model:
    """Create a new Model definition"""
    model_objects = bootstrap.MODEL_OBJECTS

    if any(d.id == model.id for d in model_objects):
        raise ValueError(f"Model: {model.id} already exists.")

    if not model.openai_compat:
        openai_compat = next(
            (model_config.openai_compat for model_config in model_objects if model_config.api == model.api),
            False,
        )
        model.openai_compat = openai_compat
    model_objects.append(model)

    return get_model(model_id=model.id, model_type=model.type)


def delete_model(model_id: schema.ModelIdType) -> None:
    """Remove model from model objects"""
    model_objects = bootstrap.MODEL_OBJECTS
    bootstrap.MODEL_OBJECTS = [model for model in model_objects if model.id != model_id]


def get_key_value(
    model_objects: list[schema.ModelAccess],
    model_id: schema.ModelIdType,
    model_key: str,
) -> str:
    """Return a models key value of its configuration"""
    for model in model_objects:
        if model.id == model_id:
            return getattr(model, model_key, None)
    return None


def get_client(model_config: dict, oci_config: schema.OracleCloudSettings, giskard: bool = False) -> BaseChatModel:
    """Retrieve model configuration"""
    logger.debug("Model Config: %s; OCI Config: %s; Giskard: %s", model_config, oci_config, giskard)
    model_objects = bootstrap.MODEL_OBJECTS

    model_id = model_config["model"]
    model_api = get_key_value(model_objects, model_id, "api")
    model_api_key = get_key_value(model_objects, model_id, "api_key")
    model_url = get_key_value(model_objects, model_id, "url")

    # Determine if configuring an embedding model
    try:
        embedding = model_config["enabled"]
    except (AttributeError, KeyError):
        embedding = False

    # schema.Model Classes
    model_classes = {}
    if not embedding:
        logger.debug("Configuring LL schema.Model")
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
                ll_common_params[key] = model_config[key] or get_key_value(model_objects, model_id, key)
            except KeyError:
                # Mainly for embeddings
                continue
        logger.debug("LL schema.Model Parameters: %s", ll_common_params)
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
                client=oci.init_genai_client(oci_cfg),
                compartment=oci_cfg.compartment,
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
                client=oci.init_genai_client(oci_cfg),
                compartment=oci_cfg.compartment,
            ),
        }

    try:
        if giskard:
            logger.debug("Creating Giskard Client for %s in %s", model_api, model_classes)
            giskard_key = model_api_key or "giskard"
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
