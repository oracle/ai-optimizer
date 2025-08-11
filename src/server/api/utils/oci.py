"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore genai ocids ocid

import os
from typing import Union
import urllib3.exceptions

import oci

from server.api.core.oci import OciException

from common.schema import OracleCloudSettings
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("api.utils.oci")


def init_client(
    client_type: Union[
        oci.object_storage.ObjectStorageClient,
        oci.identity.IdentityClient,
        oci.generative_ai_inference.GenerativeAiInferenceClient,
    ],
    config: OracleCloudSettings = None,
) -> Union[
    oci.object_storage.ObjectStorageClient,
    oci.identity.IdentityClient,
    oci.generative_ai_inference.GenerativeAiInferenceClient,
]:
    """Initialize OCI Client with either user or Token"""
    # connection timeout to 1 seconds and the read timeout to 60 seconds
    # Retries and timeouts should be handled on the client side otherwise they conflict
    client_kwargs = {
        "retry_strategy": oci.retry.NoneRetryStrategy(),
        "timeout": (1, 180),
    }

    # OCI GenAI
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
        if config_json["authentication"] == "instance_principal":
            logger.info("OCI Authentication with Instance Principal")
            instance_signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
            client = client_type(config={}, signer=instance_signer, **client_kwargs)
            if not config.tenancy:
                config.tenancy = instance_signer.tenancy_id
        elif config_json["authentication"] == "oke_workload_identity":
            logger.info("OCI Authentication with Workload Identity")
            oke_workload_signer = oci.auth.signers.get_oke_workload_identity_resource_principal_signer()
            client = client_type(config={"region": config_json["region"]}, signer=oke_workload_signer)
        elif config_json["authentication"] == "security_token" and config_json["security_token_file"]:
            logger.info("OCI Authentication with Security Token")
            token = None
            with open(config_json["security_token_file"], "r", encoding="utf-8") as f:
                token = f.read()
            private_key = oci.signer.load_private_key_from_file(config_json["key_file"])
            signer = oci.auth.signers.SecurityTokenSigner(token, private_key)
            client = client_type(config={"region": config_json["region"]}, signer=signer, **client_kwargs)
        else:
            logger.info("OCI Authentication as Standard")
            client = client_type(config_json, **client_kwargs)
    except oci.exceptions.InvalidConfig as ex:
        raise OciException(status_code=400, detail=f"Invalid Config: {str(ex)}") from ex

    return client


def init_genai_client(config: OracleCloudSettings) -> oci.generative_ai_inference.GenerativeAiInferenceClient:
    """Initialise OCI GenAI Client"""
    client_type = oci.generative_ai_inference.GenerativeAiInferenceClient
    return init_client(client_type, config)


def get_namespace(config: OracleCloudSettings = None) -> str:
    """Get the Object Storage Namespace.  Also used for testing AuthN"""
    logger.info("Getting Object Storage Namespace")
    client_type = oci.object_storage.ObjectStorageClient
    try:
        client = init_client(client_type, config)
        namespace = client.get_namespace().data
        logger.info("OCI: Namespace = %s", namespace)
    except oci.exceptions.InvalidConfig as ex:
        raise OciException(status_code=400, detail=f"Invalid Config") from ex
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

    return namespace


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
    if not hasattr(config, "genai_compartment_id") or not config.genai_compartment_id:
        raise OciException(status_code=400, detail="Missing genai_compartment_id")

    genai_models = []
    if regional:
        # Limit models to configured region
        if not hasattr(config, "genai_region") or not config.genai_region:
            raise OciException(status_code=400, detail="Missing genai_region")
        regions = [{"region_name": config.genai_region}]
    else:
        # Limit models to subscribed regions
        regions = get_regions(config)

    for region in regions:
        region_config = dict(config)
        region_config["region"] = region["region_name"]
        client = oci.generative_ai.GenerativeAiClient(region_config)
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
            # Identify all display_names that have been deprecated
            excluded_display_names = set()
            for model in response.data.items:
                if model.time_deprecated or model.time_dedicated_retired or model.time_on_demand_retired:
                    excluded_display_names.add(model.display_name)

            # Build our list of models
            for model in response.data.items:
                # note that langchain_community.llms.oci_generative_ai only supports meta/cohere models
                if model.display_name not in excluded_display_names and model.vendor in ["meta", "cohere"]:
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
        except oci.exceptions.ServiceError:
            logger.info("Region: %s has no GenAI services", region["region_name"])
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
