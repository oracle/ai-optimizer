"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore ollama, pplx, huggingface, genai, giskard, keepdim

from typing import Optional
import io
import base64
from pathlib import Path
from PIL import Image
import torch

from openai import OpenAI
from transformers import CLIPProcessor, CLIPModel

from langchain.embeddings.base import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_cohere import ChatCohere, CohereEmbeddings
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_huggingface import HuggingFaceEndpointEmbeddings
from langchain_community.chat_models.oci_generative_ai import ChatOCIGenAI
from langchain_community.embeddings.oci_generative_ai import OCIGenAIEmbeddings

from giskard.llm.client.openai import OpenAIClient

from server.utils.oci import init_genai_client
from common.schema import ModelNameType, ModelTypeType, Model, ModelAccess, OracleCloudSettings
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("server.utils.models")


#####################################################
# Classes
#####################################################
class CLIPImageEmbeddings(Embeddings):
    """Custom Local Embedding for Images"""

    def __init__(self, model_name="openai/clip-vit-base-patch32"):
        self.model = CLIPModel.from_pretrained(model_name, local_files_only=True)
        self.model.eval()
        self.processor = CLIPProcessor.from_pretrained(model_name, local_files_only=True)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embedding Images"""
        try:
            logger.debug("Processing embed_documents: %s", texts)
            image = Image.open(io.BytesIO(Path(texts[0]).read_bytes())).convert("RGB")
            inputs = self.processor(images=image, return_tensors="pt")
            with torch.no_grad():
                feats = self.model.get_image_features(**inputs)
            feats = feats / feats.norm(p=2, dim=-1, keepdim=True)
            # return feats[0].tolist()
            return [feats[0].cpu().numpy().tolist()]
        except FileNotFoundError:
            logger.error("CLIP Embedding FileNotFound: %s:", texts[0])
            return [[0.0] * self.model.visual_projection.out_features]

    def embed_query(self, text: str) -> float:
        """User prompt call"""
        logger.debug("Processing embed_query: %s", text)
        if text.startswith("data:") and ";base64," in text:
            try:
                base64_data = text.split(",", 1)[1]
                decoded_bytes = base64.b64decode(base64_data)
                image = Image.open(io.BytesIO(decoded_bytes))
                inputs = self.processor(images=image, return_tensors="pt")
                with torch.no_grad():
                    feats = self.model.get_image_features(**inputs)
                feats = feats / feats.norm(p=2, dim=-1, keepdim=True)
            except Exception as ex:
                logger.error("Failed to decode base64 input: %s", ex)
                return [0.0] * self.model.visual_projection.out_features
        else:
            inputs = self.processor(text=text, return_tensors="pt", padding=True, truncation=True)
            with torch.no_grad():
                feats = self.model.get_text_features(**inputs)
            feats = feats / feats.norm(p=2, dim=-1, keepdim=True)

        return feats[0].cpu().numpy().tolist()


#####################################################
# Functions
#####################################################
async def apply_filter(
    models_all: list[Model],
    model_name: Optional[ModelNameType] = None,
    model_type: Optional[ModelTypeType] = None,
) -> list[Model]:
    """Used in direct call from list_models and agents.models"""
    logger.debug("%i models are defined", len(models_all))
    models_all = [
        model
        for model in models_all
        if (model_name is None or model.name == model_name) and (model_type is None or model.type == model_type)
    ]
    logger.debug("%i models after filtering", len(models_all))
    return models_all


async def get_key_value(
    model_objects: list[ModelAccess],
    model_name: ModelNameType,
    model_key: str,
) -> str:
    """Return a models key value of its configuration"""
    for model in model_objects:
        if model.name == model_name:
            return getattr(model, model_key, None)
    return None


async def get_client(
    model_objects: list[ModelAccess], model_config: dict, oci_config: OracleCloudSettings, giskard: bool = False
) -> BaseChatModel:
    """Retrieve model configuration"""
    logger.debug("Model Config: %s; Giskard: %s", model_config, giskard)
    model_name = model_config["model"]
    model_api = await get_key_value(model_objects, model_name, "api")
    model_api_key = await get_key_value(model_objects, model_name, "api_key")
    model_url = await get_key_value(model_objects, model_name, "url")

    # Determine if configuring an embedding model
    try:
        embedding = model_config["enabled"]
    except (AttributeError, KeyError):
        embedding = False

    # Model Classes
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
                ll_common_params[key] = model_config[key] or await get_key_value(model_objects, model_name, key)
            except KeyError:
                # Mainly for embeddings
                continue
        logger.debug("LL Model Parameters: %s", ll_common_params)
        model_classes = {
            "OpenAI": lambda: ChatOpenAI(model=model_name, api_key=model_api_key, **ll_common_params),
            "CompatOpenAI": lambda: ChatOpenAI(
                model=model_name, base_url=model_url, api_key=model_api_key or "api_compat", **ll_common_params
            ),
            "Cohere": lambda: ChatCohere(model=model_name, cohere_api_key=model_api_key, **ll_common_params),
            "ChatOllama": lambda: ChatOllama(
                model=model_name,
                base_url=model_url,
                **ll_common_params,
                num_predict=ll_common_params["max_completion_tokens"],
            ),
            "Perplexity": lambda: ChatOpenAI(
                model=model_name, base_url=model_url, api_key=model_api_key, **ll_common_params
            ),
            "ChatOCIGenAI": lambda oci_cfg=oci_config: ChatOCIGenAI(
                model_id=model_name,
                client=init_genai_client(oci_cfg),
                compartment_id=oci_cfg.compartment_id,
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
            "OpenAIEmbeddings": lambda: OpenAIEmbeddings(model=model_name, api_key=model_api_key),
            "CompatOpenAIEmbeddings": lambda: OpenAIEmbeddings(
                model=model_name,
                base_url=model_url,
                api_key=model_api_key or "api_compat",
                check_embedding_ctx_length=False,
            ),
            "CohereEmbeddings": lambda: CohereEmbeddings(model=model_name, cohere_api_key=model_api_key),
            "OllamaEmbeddings": lambda: OllamaEmbeddings(model=model_name, base_url=model_url),
            "HuggingFaceEndpointEmbeddings": lambda: HuggingFaceEndpointEmbeddings(model=model_url),
            "OCIGenAIEmbeddings": lambda oci_cfg=oci_config: OCIGenAIEmbeddings(
                model_id=model_name,
                client=init_genai_client(oci_cfg),
                compartment_id=oci_cfg.compartment_id,
            ),
            "CLIPEmbeddings": lambda: CLIPImageEmbeddings(),
        }

    try:
        if giskard:
            logger.debug("Creating Giskard Client for %s in %s", model_api, model_classes)
            giskard_key = model_api_key or "giskard"
            _client = OpenAI(api_key=giskard_key, base_url=f"{model_url}/v1")
            client = OpenAIClient(model=model_name, client=_client)
        else:
            logger.debug("Searching for %s in %s", model_api, model_classes)
            client = model_classes[model_api]()
            logger.debug("Model Client: %s", client)
        return client
    except (UnboundLocalError, KeyError):
        logger.error("Unable to find client; expect trouble!")
        return None
