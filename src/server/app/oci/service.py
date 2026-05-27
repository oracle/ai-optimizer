"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

OCI service functions for GenAI model discovery and creation.
"""
# spell-checker: ignore genai

import logging

import oci.generative_ai
import oci.identity
import oci.retry
import urllib3.exceptions

from server.app.core.settings import settings
from server.app.models.registry import register_model
from server.app.models.schemas import ModelConfig

from .client import init_client
from .schemas import OciProfileConfig, genai_inference_endpoint

LOGGER = logging.getLogger(__name__)


def get_regions(profile: OciProfileConfig) -> list[dict]:
    """Retrieve a list of subscribed regions."""
    client = init_client(oci.identity.IdentityClient, profile)
    resp = client.list_region_subscriptions(profile.tenancy)
    regions = resp.data if resp else []
    return [
        {
            "is_home_region": region.is_home_region,
            "region_key": region.region_key,
            "region_name": region.region_name,
            "status": region.status,
        }
        for region in regions
    ]


def get_genai_models(profile: OciProfileConfig, regional: bool = False) -> list[dict]:
    """Get a list of GenAI models across subscribed regions (or a single region if regional=True)."""
    if not profile.genai_compartment_id:
        raise ValueError("Missing genai_compartment_id")

    if regional:
        if not profile.genai_region:
            raise ValueError("Missing genai_region")
        regions = [{"region_name": profile.genai_region}]
    else:
        regions = get_regions(profile)

    genai_models = []
    seen_models = set()

    for region in regions:
        region_profile = profile.model_copy(deep=True)
        region_profile.region = region["region_name"]
        client = init_client(oci.generative_ai.GenerativeAiClient, region_profile)
        LOGGER.info(
            "Checking Region: %s; Compartment: %s for GenAI services",
            region["region_name"],
            profile.genai_compartment_id,
        )
        try:
            resp = client.list_models(
                compartment_id=profile.genai_compartment_id,
                lifecycle_state="ACTIVE",
                sort_order="ASC",
                sort_by="displayName",
                retry_strategy=oci.retry.NoneRetryStrategy(),
            )
            models_data = resp.data.items if resp and resp.data else []
            # Identify deprecated model names
            excluded_display_names = {
                model.display_name
                for model in models_data
                if model.time_deprecated or model.time_dedicated_retired or model.time_on_demand_retired
            }

            # Build list of models (excluding deprecated, non-ready, and duplicates)
            for model in models_data:
                model_key = (region["region_name"], model.display_name)
                if model.display_name in excluded_display_names or model_key in seen_models:
                    continue
                if getattr(model, "lifecycle_details", None) == "Creating Base Model":
                    continue

                seen_models.add(model_key)
                genai_models.append(
                    {
                        "region": region["region_name"],
                        "compartment_id": profile.genai_compartment_id,
                        "model_name": model.display_name,
                        "capabilities": model.capabilities,
                        "vendor": model.vendor,
                        "id": model.id,
                    }
                )
            LOGGER.info("Registered %i GenAI Models", len(genai_models))
        except oci.exceptions.ServiceError as ex:
            LOGGER.info("Unable to get GenAI Models in Region: %s (%s)", region["region_name"], ex.message)
        except (
            oci.exceptions.RequestException,
            oci.exceptions.ConnectTimeout,
            urllib3.exceptions.MaxRetryError,
        ):
            LOGGER.error("Timeout: Error querying GenAI services in %s", region["region_name"])

    return genai_models


async def create_genai_models(profile: OciProfileConfig) -> list[ModelConfig]:
    """Create and enable all GenAI models in the configured region.

    Caller must hold ``_settings_lock`` and is responsible for
    persisting settings and rolling back on failure.
    """
    region_models = get_genai_models(profile, regional=True)
    # Always purge previously configured OCI provider models when switching regions
    settings.model_configs = [m for m in settings.model_configs if m.provider != "oci"]

    genai_models = []
    for model in region_models:
        model_dict = {
            "provider": "oci",
            "id": model["model_name"],
            "enabled": True,
            "api_base": genai_inference_endpoint(profile.genai_region),
        }
        if "CHAT" in model["capabilities"]:
            model_dict["type"] = "ll"
            model_dict["max_input_tokens"] = 131072
        elif "TEXT_EMBEDDINGS" in model["capabilities"]:
            model_dict["type"] = "embed"
            model_dict["max_chunk_size"] = 8192
        else:
            continue

        new_model = ModelConfig(**model_dict)
        register_model(new_model)
        genai_models.append(new_model)

    return genai_models
