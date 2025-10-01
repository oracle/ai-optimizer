"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore ocid genai

from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import JSONResponse

import server.api.core.oci as core_oci
import server.api.utils.embed as utils_embed
import server.api.utils.oci as utils_oci
import server.api.utils.models as utils_models

from common import schema
from common import logging_config

logger = logging_config.logging.getLogger("endpoints.v1.oci")

# Validate the DEFAULT OCI Profile and get models
try:
    default_config = core_oci.get_oci(auth_profile="DEFAULT")
    _ = utils_oci.get_namespace(config=default_config)
    _ = utils_models.create_genai(config=default_config)
except utils_oci.OciException:
    pass

auth = APIRouter()


@auth.get(
    "",
    description="View OCI Configuration",
    response_model=list[schema.OracleCloudSettings],
)
async def oci_list() -> list[schema.OracleCloudSettings]:
    """List OCI Configuration"""
    logger.debug("Received oci_list")
    try:
        return core_oci.get_oci()
    except ValueError as ex:
        raise HTTPException(status_code=404, detail=f"OCI: {str(ex)}.") from ex


@auth.get(
    "/{auth_profile}",
    description="View OCI Profile Configuration",
    response_model=schema.OracleCloudSettings,
)
async def oci_get(
    auth_profile: schema.OCIProfileType,
) -> schema.OracleCloudSettings:
    """List OCI Configuration"""
    logger.debug("Received oci_get - auth_profile: %s", auth_profile)
    try:
        return core_oci.get_oci(auth_profile=auth_profile)
    except ValueError as ex:
        raise HTTPException(status_code=404, detail=f"OCI: {str(ex)}.") from ex


@auth.get(
    "/regions/{auth_profile}",
    description="Get Subscribed OCI Regions",
    response_model=list,
)
async def oci_list_regions(
    auth_profile: schema.OCIProfileType,
) -> list:
    """Return a list of compartments"""
    logger.debug("Received oci_list_regions - auth_profile: %s", auth_profile)
    try:
        oci_config = await oci_get(auth_profile=auth_profile)
        regions = utils_oci.get_regions(oci_config)
        return regions
    except utils_oci.OciException as ex:
        raise HTTPException(status_code=ex.status_code, detail=f"OCI: {ex.detail}.") from ex


@auth.get(
    "/genai/{auth_profile}",
    description="Get OCI GenAI Services Models",
    response_model=list,
)
async def oci_list_genai(
    auth_profile: schema.OCIProfileType,
) -> list:
    """Return a list of compartments"""
    logger.debug("Received oci_list_genai - auth_profile: %s", auth_profile)
    try:
        oci_config = await oci_get(auth_profile=auth_profile)
        all_models = utils_oci.get_genai_models(oci_config, regional=False)
        return all_models
    except utils_oci.OciException as ex:
        raise HTTPException(status_code=ex.status_code, detail=f"OCI: {ex.detail}.") from ex


@auth.get(
    "/compartments/{auth_profile}",
    description="Get OCI Compartments",
    response_model=dict,
)
async def oci_list_compartments(
    auth_profile: schema.OCIProfileType,
) -> dict:
    """Return a list of compartments"""
    logger.debug("Received oci_list_compartments - auth_profile: %s", auth_profile)
    try:
        oci_config = await oci_get(auth_profile=auth_profile)
        compartments = utils_oci.get_compartments(oci_config)
        return compartments
    except utils_oci.OciException as ex:
        raise HTTPException(status_code=ex.status_code, detail=f"OCI: {ex.detail}.") from ex


@auth.get(
    "/buckets/{compartment_ocid}/{auth_profile}",
    description="Get OCI Object Storage buckets in Compartment OCID",
    response_model=list,
)
async def oci_list_buckets(
    auth_profile: schema.OCIProfileType,
    compartment_ocid: str,
) -> list:
    """Return a list of buckets; Validate OCID using Pydantic class"""
    logger.debug("Received oci_list_buckets - auth_profile: %s; compartment_ocid: %s", auth_profile, compartment_ocid)
    try:
        compartment_obj = schema.OracleResource(ocid=compartment_ocid)
        oci_config = await oci_get(auth_profile=auth_profile)
        buckets = utils_oci.get_buckets(compartment_obj.ocid, oci_config)
        return buckets
    except utils_oci.OciException as ex:
        raise HTTPException(status_code=ex.status_code, detail=f"OCI: {ex.detail}.") from ex


@auth.get(
    "/objects/{bucket_name}/{auth_profile}",
    description="Get OCI Object Storage buckets objects",
    response_model=list,
)
async def oci_list_bucket_objects(
    auth_profile: schema.OCIProfileType,
    bucket_name: str,
) -> list:
    """Return a list of bucket objects; Validate OCID using Pydantic class"""
    logger.debug("Received oci_list_bucket_objects - auth_profile: %s; bucket_name: %s", auth_profile, bucket_name)
    try:
        oci_config = await oci_get(auth_profile=auth_profile)
        objects = utils_oci.get_bucket_objects(bucket_name, oci_config)
        return objects
    except utils_oci.OciException as ex:
        raise HTTPException(status_code=ex.status_code, detail=f"OCI: {ex.detail}.") from ex


@auth.patch(
    "/{auth_profile}",
    description="Update, Test, Set as Default OCI Configuration",
    response_model=schema.OracleCloudSettings,
)
async def oci_profile_update(
    auth_profile: schema.OCIProfileType,
    payload: schema.OracleCloudSettings,
) -> schema.OracleCloudSettings:
    """Update OCI Configuration"""
    logger.debug("Received oci_update - auth_profile: %s; payload %s", auth_profile, payload)

    oci_config = await oci_get(auth_profile=auth_profile)

    try:
        namespace = utils_oci.get_namespace(payload)
        oci_config.namespace = namespace
        for key, value in payload.model_dump().items():
            if value not in ("", None):
                setattr(oci_config, key, value)
    except utils_oci.OciException as ex:
        oci_config.namespace = None
        raise HTTPException(status_code=ex.status_code, detail=f"OCI: {ex.detail}.") from ex
    except AttributeError as ex:
        oci_config.namespace = None
        raise HTTPException(status_code=400, detail="OCI: Invalid Payload.") from ex

    return oci_config


@auth.post(
    "/objects/download/{bucket_name}/{auth_profile}",
    description="Download files from Object Storage",
)
async def oci_download_objects(
    bucket_name: str,
    auth_profile: schema.OCIProfileType,
    request: list[str],
    client: schema.ClientIdType = Header(default="server"),
) -> JSONResponse:
    """Download files from Object Storage"""
    logger.debug(
        "Received oci_download_objects - auth_profile: %s; bucket_name: %s; request: %s",
        auth_profile,
        bucket_name,
        request,
    )
    oci_config = await oci_get(auth_profile=auth_profile)
    # Files should be placed in the embedding folder
    temp_directory = utils_embed.get_temp_directory(client, "embedding")
    for object_name in request:
        utils_oci.get_object(temp_directory, object_name, bucket_name, oci_config)

    downloaded_files = [f.name for f in temp_directory.iterdir() if f.is_file()]
    return JSONResponse(status_code=200, content=downloaded_files)


@auth.post(
    "/genai/{auth_profile}",
    description="Enable OCI GenAI models",
    response_model=list[schema.Model],
)
async def oci_create_genai_models(
    auth_profile: schema.OCIProfileType,
) -> list[schema.Model]:
    """Return a list of compartments"""
    logger.debug("Received oci_create_genai_models - auth_profile: %s", auth_profile)
    try:
        oci_config = await oci_get(auth_profile=auth_profile)
        enabled_models = utils_models.create_genai(oci_config)
        return enabled_models
    except utils_oci.OciException as ex:
        raise HTTPException(status_code=ex.status_code, detail=f"OCI: {ex.detail}.") from ex
