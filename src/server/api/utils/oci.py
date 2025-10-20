"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore genai ocids ocid

import os
import base64
import json
from typing import Union, Optional
import urllib3.exceptions

import oci

from server.bootstrap import bootstrap
from common.schema import OracleCloudSettings, ClientIdType, OCIProfileType
from common import logging_config

logger = logging_config.logging.getLogger("api.utils.oci")


#####################################################
# Exceptions
#####################################################
class OciException(Exception):
    """Custom OCI Exceptions to be passed to HTTPException"""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


#####################################################
# CRUD Functions
#####################################################
def get(
    client: Optional[ClientIdType] = None, auth_profile: Optional[OCIProfileType] = None
) -> Union[list[OracleCloudSettings], OracleCloudSettings]:
    """
    Return all OCI Settings if no client or auth_profile is specified.
    Raises ValueError if both client and auth_profile are provided.
    If client is provided, derives auth_profile and returns matching OCI settings.
    If auth_profile is provided, returns matching OCI settings.
    Raises ValueError if no matching OCI found.
    """
    logger.debug("Getting OCI config for client: %s; auth_profile: %s", client, auth_profile)
    if client is not None and auth_profile is not None:
        raise ValueError("provide either 'client' or 'auth_profile', not both")

    oci_objects = bootstrap.OCI_OBJECTS
    if client is not None:
        # Get client settings directly from SETTINGS_OBJECTS
        logger.debug("Looking for client %s in SETTINGS_OBJECTS", client)
        logger.debug(
            "SETTINGS_OBJECTS has %d entries: %s",
            len(bootstrap.SETTINGS_OBJECTS),
            [s.client for s in bootstrap.SETTINGS_OBJECTS],
        )
        client_settings = next((s for s in bootstrap.SETTINGS_OBJECTS if s.client == client), None)
        if not client_settings:
            available_clients = [s.client for s in bootstrap.SETTINGS_OBJECTS]
            raise ValueError(f"client {client} not found in SETTINGS_OBJECTS with clients: {available_clients}")

        derived_auth_profile = (
            getattr(client_settings.oci, "auth_profile", "DEFAULT") if client_settings.oci else "DEFAULT"
        )

        matching_oci = next((oci for oci in oci_objects if oci.auth_profile == derived_auth_profile), None)
        if matching_oci is None:
            raise ValueError(f"No settings found for client '{client}' with auth_profile '{derived_auth_profile}'")
        return matching_oci

    if auth_profile is not None:
        matching_oci = next((oci for oci in oci_objects if oci.auth_profile == auth_profile), None)
        if matching_oci is None:
            raise ValueError(f"profile '{auth_profile}' not found")
        return matching_oci

    # No filters, return all
    if not oci_objects:
        raise ValueError("not configured")

    return oci_objects


#####################################################
# Utility Functions
#####################################################
def get_signer(config: OracleCloudSettings) -> Optional[object]:
    """Get OCI signer for instance principal or workload identity authentication."""

    if config.authentication == "instance_principal":
        logger.info("Creating Instance Principal signer")
        return oci.auth.signers.InstancePrincipalsSecurityTokenSigner()

    if config.authentication == "oke_workload_identity":
        logger.info("Creating OKE Workload Identity signer")
        return oci.auth.signers.get_oke_workload_identity_resource_principal_signer()

    # API key or security token authentication - no signer needed
    return None


def init_client(
    client_type: Union[
        oci.object_storage.ObjectStorageClient,
        oci.identity.IdentityClient,
        oci.generative_ai_inference.GenerativeAiInferenceClient,
        oci.generative_ai.GenerativeAiClient,
    ],
    config: OracleCloudSettings = None,
) -> Union[
    oci.object_storage.ObjectStorageClient,
    oci.identity.IdentityClient,
    oci.generative_ai_inference.GenerativeAiInferenceClient,
    oci.generative_ai.GenerativeAiClient,
]:
    """Initialize OCI Client with either user or Token"""
    # connection timeout to 1 seconds and the read timeout to 60 seconds
    # Retries and timeouts should be handled on the client side otherwise they conflict
    client_kwargs = {
        "retry_strategy": oci.retry.NoneRetryStrategy(),
        "timeout": (1, 180),
    }

    # OCI GenAI (for model calling)
    if (
        client_type == oci.generative_ai_inference.GenerativeAiInferenceClient
        and config.genai_compartment_id
        and config.genai_region
    ):
        client_kwargs["service_endpoint"] = f"https://inference.generativeai.{config.genai_region}.oci.oraclecloud.com"

    # Initialize Client (Workload Identity, Token and API)
    config_json = config.model_dump(exclude_none=False)
    client = None
    try:
        # Get signer for instance principal or workload identity
        signer = get_signer(config)

        if signer:
            # Use signer-based authentication
            client = client_type(config={"region": config_json["region"]}, signer=signer, **client_kwargs)

            # Set tenancy from signer if not already set
            if not config.tenancy:
                if config_json["authentication"] == "instance_principal":
                    config.tenancy = signer.tenancy_id
                elif config_json["authentication"] == "oke_workload_identity":
                    token = signer.get_security_token()
                    payload_part = token.split(".")[1]
                    padding = "=" * (-len(payload_part) % 4)
                    decoded_bytes = base64.urlsafe_b64decode(payload_part + padding)
                    payload = json.loads(decoded_bytes)
                    config.tenancy = payload.get("tenant")
        elif config_json["authentication"] == "security_token" and config_json["security_token_file"]:
            logger.info("OCI Authentication with Security Token")
            token = None
            with open(config_json["security_token_file"], "r", encoding="utf-8") as f:
                token = f.read()
            private_key = oci.signer.load_private_key_from_file(config_json["key_file"])
            sec_token_signer = oci.auth.signers.SecurityTokenSigner(token, private_key)
            client = client_type(config={"region": config_json["region"]}, signer=sec_token_signer, **client_kwargs)
        else:
            logger.info("OCI Authentication as Standard")
            client = client_type(config_json, **client_kwargs)
    except oci.exceptions.InvalidConfig as ex:
        raise OciException(status_code=400, detail=f"Invalid Config: {str(ex)}") from ex

    return client


def init_genai_client(config: OracleCloudSettings) -> oci.generative_ai_inference.GenerativeAiInferenceClient:
    """Initialise OCI GenAI Client; used by models"""
    client_type = oci.generative_ai_inference.GenerativeAiInferenceClient
    return init_client(client_type, config)


def get_namespace(config: OracleCloudSettings) -> str:
    """Get the Object Storage Namespace.  Also used for testing AuthN"""
    logger.info("Getting Object Storage Namespace")
    client_type = oci.object_storage.ObjectStorageClient
    try:
        client = init_client(client_type, config)
        config.namespace = client.get_namespace().data
        logger.info("OCI: Namespace = %s", config.namespace)
    except oci.exceptions.InvalidConfig as ex:
        raise OciException(status_code=400, detail="Invalid Config") from ex
    except oci.exceptions.ServiceError as ex:
        raise OciException(status_code=401, detail="AuthN Error") from ex
    except FileNotFoundError as ex:
        raise OciException(status_code=400, detail="Invalid Key Path") from ex
    except UnboundLocalError as ex:
        raise OciException(status_code=500, detail="No Configuration") from ex
    except oci.exceptions.RequestException as ex:
        raise OciException(status_code=503, detail=ex) from ex
    except Exception as ex:
        raise OciException(status_code=500, detail=str(ex)) from ex

    return config.namespace


def get_regions(config: OracleCloudSettings = None) -> list[dict]:
    """Retrieve a list of subscribed regions"""
    client_type = oci.identity.IdentityClient
    client = init_client(client_type, config)

    tenancy_id = config.tenancy
    response = client.list_region_subscriptions(tenancy_id).data
    return [
        {
            "is_home_region": region.is_home_region,
            "region_key": region.region_key,
            "region_name": region.region_name,
            "status": region.status,
        }
        for region in response
    ]


def get_genai_models(config: OracleCloudSettings, regional: bool = False) -> list:
    """Get a list of GenAI models in a regions compartment"""
    if not config.genai_compartment_id:
        raise OciException(status_code=400, detail="Missing genai_compartment_id")

    # Determine regions to query
    if regional:
        if not config.genai_region:
            raise OciException(status_code=400, detail="Missing genai_region")
        regions = [{"region_name": config.genai_region}]
    else:
        regions = get_regions(config)

    genai_models = []
    seen_models = set()  # Track unique models by (region, display_name)

    for region in regions:
        region_config = config.model_copy(deep=True)
        region_config.region = region["region_name"]
        client = init_client(oci.generative_ai.GenerativeAiClient, region_config)
        logger.info(
            "Checking Region: %s; Compartment: %s for GenAI services",
            region["region_name"],
            config.genai_compartment_id,
        )
        try:
            response = client.list_models(
                compartment_id=config.genai_compartment_id,
                capability=["TEXT_EMBEDDINGS", "CHAT"],
                lifecycle_state="ACTIVE",
                sort_order="ASC",
                sort_by="displayName",
                retry_strategy=oci.retry.NoneRetryStrategy(),
            )
            # Identify deprecated model names
            excluded_display_names = {
                model.display_name
                for model in response.data.items
                if model.time_deprecated or model.time_dedicated_retired or model.time_on_demand_retired
            }

            # Build list of models (excluding deprecated ones and duplicates)
            for model in response.data.items:
                model_key = (region["region_name"], model.display_name)
                # Skip if deprecated, duplicate, or cohere model without TEXT_EMBEDDINGS
                if (
                    model.display_name in excluded_display_names
                    or model_key in seen_models
                    or (model.vendor == "cohere" and "TEXT_EMBEDDINGS" not in model.capabilities)
                ):
                    continue

                seen_models.add(model_key)
                genai_models.append(
                    {
                        "region": region["region_name"],
                        "compartment_id": config.genai_compartment_id,
                        "model_name": model.display_name,
                        "capabilities": model.capabilities,
                        "vendor": model.vendor,
                        "id": model.id,
                    }
                )
            logger.info("Registered %i GenAI Models", len(genai_models))
        except oci.exceptions.ServiceError as ex:
            logger.info("Unable to get GenAI Models in Region: %s (%s)", region["region_name"], ex.message)
        except (oci.exceptions.RequestException, urllib3.exceptions.MaxRetryError):
            logger.error("Timeout: Error querying GenAI services in %s", region["region_name"])

    return genai_models


def get_compartments(config: OracleCloudSettings = None) -> set:
    """Retrieve a list of compartments"""
    client_type = oci.identity.IdentityClient
    client = init_client(client_type, config)

    compartment_paths = {}
    response = client.list_compartments(
        compartment_id=config.tenancy,
        compartment_id_in_subtree=True,
        access_level="ACCESSIBLE",
        sort_by="NAME",
        sort_order="ASC",
        lifecycle_state="ACTIVE",
    )
    compartments = response.data

    # Create a dictionary to map compartment_id ID to compartment_id details
    compartment_dict = {compartment_id.id: compartment_id for compartment_id in compartments}

    def construct_path(compartment_id):
        """Function to construct the full path of a compartment_id"""
        path = []
        current = compartment_id
        while current:
            path.append(current.name)
            current = compartment_dict.get(current.compartment_id)
        return " / ".join(reversed(path))

    # Create a set with full paths as keys and OCIDs as values
    compartment_paths = {construct_path(compartment_id): compartment_id.id for compartment_id in compartments}
    logger.info("Returning %i Compartments", len(compartment_paths))
    return compartment_paths


def get_buckets(compartment_id: str, config: OracleCloudSettings = None) -> list:
    """Get a list of buckets"""
    client_type = oci.object_storage.ObjectStorageClient
    client = init_client(client_type, config)

    logger.info("Getting Buckets in %s", compartment_id)
    client = init_client(client_type, config)
    bucket_names = []
    try:
        response = client.list_buckets(namespace_name=config.namespace, compartment_id=compartment_id, fields=["tags"])
        buckets = response.data
        for bucket in buckets:
            freeform_tags = bucket.freeform_tags or {}
            if freeform_tags.get("genai_chunk") != "true":
                bucket_names.append(bucket.name)
    except oci.exceptions.ServiceError as ex:
        # No Access to Buckets in Compartment
        raise OciException(status_code=401, detail="AuthN Error") from ex

    return bucket_names


def get_bucket_objects(bucket_name: str, config: OracleCloudSettings = None) -> list:
    """Get a list of Bucket Objects"""
    client_type = oci.object_storage.ObjectStorageClient
    client = init_client(client_type, config)

    object_names = []
    try:
        response = client.list_objects(
            namespace_name=config.namespace,
            bucket_name=bucket_name,
        )
        objects = response.data.objects
        # TODO(gotsysba) - filter out non-supported objects
        object_names = [object.name for object in objects]
    except oci.exceptions.ServiceError:
        logger.debug("Bucket %s not found.  Will create on upload.", bucket_name)

    return object_names


def get_bucket_objects_with_metadata(bucket_name: str, config: OracleCloudSettings = None) -> list[dict]:
    """Get a list of Bucket Objects with metadata for change detection"""
    client_type = oci.object_storage.ObjectStorageClient
    client = init_client(client_type, config)

    objects_metadata = []
    try:
        response = client.list_objects(
            namespace_name=config.namespace,
            bucket_name=bucket_name,
        )
        objects = response.data.objects

        # Filter supported file types and add metadata
        supported_extensions = {'.pdf', '.html', '.md', '.txt', '.csv', '.png', '.jpg', '.jpeg'}

        for obj in objects:
            _, ext = os.path.splitext(obj.name.lower())
            if ext in supported_extensions:
                objects_metadata.append({
                    "name": obj.name,
                    "size": obj.size,
                    "etag": obj.etag,
                    "time_modified": obj.time_modified.isoformat() if obj.time_modified else None,
                    "md5": obj.md5,
                    "extension": ext[1:]  # Remove the dot
                })
    except oci.exceptions.ServiceError:
        logger.debug("Bucket %s not found.", bucket_name)

    return objects_metadata


def detect_changed_objects(
    current_objects: list[dict],
    processed_objects: dict
) -> tuple[list[dict], list[dict]]:
    """
    Detect new and modified objects by comparing current bucket state
    with previously processed objects metadata

    Args:
        current_objects: Current objects from OCI bucket with metadata
        processed_objects: Dict mapping object names to their last processed metadata

    Returns:
        Tuple of (new_objects, modified_objects)
    """
    new_objects = []
    modified_objects = []

    for obj in current_objects:
        obj_name = obj["name"]

        if obj_name not in processed_objects:
            # New object
            new_objects.append(obj)
        else:
            # Check if object has been modified
            last_processed = processed_objects[obj_name]

            # If old format (no etag), skip - assume unchanged to avoid duplicates
            if last_processed.get("etag") is None and last_processed.get("time_modified") is None:
                logger.debug(f"Skipping {obj_name} - found in old metadata format (assumed unchanged)")
                continue

            # Compare etag and modification time
            if (obj["etag"] != last_processed.get("etag") or
                obj["time_modified"] != last_processed.get("time_modified")):
                modified_objects.append(obj)

    logger.info("Found %d new objects and %d modified objects", len(new_objects), len(modified_objects))
    return new_objects, modified_objects


def get_object(directory: str, object_name: str, bucket_name: str, config: OracleCloudSettings = None) -> list:
    """Download Object Storage Object"""
    client_type = oci.object_storage.ObjectStorageClient
    client = init_client(client_type, config)

    file_name = os.path.basename(object_name)
    file_path = os.path.join(directory, file_name)

    response = client.get_object(namespace_name=config.namespace, bucket_name=bucket_name, object_name=object_name)
    with open(file_path, "wb") as f:
        for content in response.data.raw.stream(1024 * 1024, decode_content=False):
            f.write(content)
    file_size = os.path.getsize(file_path)
    logger.info("Downloaded %s to %s (%i bytes)", file_name, file_path, file_size)

    return file_path
