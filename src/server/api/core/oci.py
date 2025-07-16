"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore genai, ocids

import os
from typing import Optional, Union

import oci

from server.api.core import bootstrap, settings
from common.schema import OracleCloudSettings, ClientIdType, OCIProfileType
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("api.core.oci")


class OciException(Exception):
    """Custom OCI Exception"""

    def __init__(self, message):
        super().__init__(message)


def get_oci(
    client: Optional[ClientIdType] = None, auth_profile: Optional[OCIProfileType] = None
) -> Union[list[OracleCloudSettings], OracleCloudSettings]:
    """
    Return all OCI Settings if no client or auth_profile is specified.
    Raises ValueError if both client and auth_profile are provided.
    If client is provided, derives auth_profile and returns matching OCI settings.
    If auth_profile is provided, returns matching OCI settings.
    Raises ValueError if no matching OCI found.
    """
    if client is not None and auth_profile is not None:
        raise ValueError("OCI: Provide either 'client' or 'auth_profile', not both.")

    oci_objects = bootstrap.OCI_OBJECTS

    if client is not None:
        client_settings = settings.get_client_settings(client)
        derived_auth_profile = (
            getattr(client_settings.oci, "auth_profile", "DEFAULT") if client_settings.oci else "DEFAULT"
        )

        matching_oci = next((oci for oci in oci_objects if oci.auth_profile == derived_auth_profile), None)
        if matching_oci is None:
            raise ValueError(
                f"OCI: No settings found for client '{client}' with auth_profile '{derived_auth_profile}'."
            )
        return matching_oci

    if auth_profile is not None:
        matching_oci = next((oci for oci in oci_objects if oci.auth_profile == auth_profile), None)
        if matching_oci is None:
            raise ValueError(f"OCI: No settings found for auth_profile '{auth_profile}'.")
        return matching_oci

    # No filters, return all
    if not oci_objects:
        raise ValueError("OCI: Not configured.")

    return oci_objects


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
    if client_type == oci.generative_ai_inference.GenerativeAiInferenceClient and config.service_endpoint:
        client_kwargs["service_endpoint"] = config.service_endpoint

    # Initialize Client (Workload Identity, Token and API)
    config_json = config.model_dump(exclude_none=False)
    client = None
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
        raise OciException("OCI: Invalid Config") from ex
    except oci.exceptions.ServiceError as ex:
        raise OciException("OCI: AuthN Error") from ex
    except oci.exceptions.RequestException as ex:
        raise OciException("OCI: No Network Access") from ex
    except FileNotFoundError as ex:
        raise OciException("OCI: Invalid Key Path") from ex
    except UnboundLocalError as ex:
        raise OciException("OCI: No Configuration") from ex
    except Exception as ex:
        raise OciException(f"OCI: {ex}") from ex

    return namespace


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

    # Create a dictionary to map compartment ID to compartment details
    compartment_dict = {compartment.id: compartment for compartment in compartments}

    def construct_path(compartment):
        """Function to construct the full path of a compartment"""
        path = []
        current = compartment
        while current:
            path.append(current.name)
            current = compartment_dict.get(current.compartment_id)
        return " / ".join(reversed(path))

    # Create a set with full paths as keys and OCIDs as values
    compartment_paths = {construct_path(compartment): compartment.id for compartment in compartments}
    logger.info("Returning %i Compartments", len(compartment_paths))
    return compartment_paths


def get_buckets(compartment: str, config: OracleCloudSettings = None) -> list:
    """Get a list of buckets"""
    client_type = oci.object_storage.ObjectStorageClient
    client = init_client(client_type, config)

    logger.info("Getting Buckets in %s", compartment)
    client = init_client(client_type, config)
    bucket_names = []
    try:
        response = client.list_buckets(namespace_name=config.namespace, compartment_id=compartment, fields=["tags"])
        buckets = response.data
        for bucket in buckets:
            freeform_tags = bucket.freeform_tags or {}
            if freeform_tags.get("genai_chunk") != "true":
                bucket_names.append(bucket.name)
    except oci.exceptions.ServiceError as ex:
        # No Access to Buckets in Compartment
        raise OciException("OCI: AuthN Error") from ex

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
