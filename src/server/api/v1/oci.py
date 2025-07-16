"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore selectai ocid

from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import JSONResponse

from server.api.core import models
import server.api.core.oci as core_oci
from server.api.util import embed
import server.api.util.oci as util_oci

import common.schema as schema
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("endpoints.v1.oci")

auth = APIRouter()


@auth.get("/", description="View OCI Configuration", response_model=list[schema.OracleCloudSettings])
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
async def oci_get(auth_profile: schema.OCIProfileType) -> schema.OracleCloudSettings:
    """List OCI Configuration"""
    logger.debug("Received oci_get - auth_profile: %s", auth_profile)
    try:
        return core_oci.get_oci(auth_profile=auth_profile)
    except ValueError as ex:
        raise HTTPException(status_code=404, detail=f"OCI: {str(ex)}.") from ex


@auth.get(
    "/compartments/{auth_profile}",
    description="Get OCI Compartments",
    response_model=dict,
)
async def oci_list_compartments(auth_profile: schema.OCIProfileType) -> dict:
    """Return a list of compartments"""
    logger.debug("Received oci_list_compartments - auth_profile: %s", auth_profile)
    oci_config = await oci_get(auth_profile=auth_profile)
    compartments = util_oci.get_compartments(oci_config)
    return compartments


@auth.get(
    "/buckets/{compartment_ocid}/{auth_profile}",
    description="Get OCI Object Storage buckets in Compartment OCID",
    response_model=list,
)
async def oci_list_buckets(auth_profile: schema.OCIProfileType, compartment_ocid: str) -> list:
    """Return a list of buckets; Validate OCID using Pydantic class"""
    logger.debug("Received oci_list_buckets - auth_profile: %s; compartment_ocid: %s", auth_profile, compartment_ocid)
    compartment_obj = schema.OracleResource(ocid=compartment_ocid)
    oci_config = await oci_get(auth_profile=auth_profile)
    buckets = util_oci.get_buckets(compartment_obj.ocid, oci_config)
    return buckets


@auth.get(
    "/objects/{bucket_name}/{auth_profile}",
    description="Get OCI Object Storage buckets objects",
    response_model=list,
)
async def oci_list_bucket_objects(auth_profile: schema.OCIProfileType, bucket_name: str) -> list:
    """Return a list of bucket objects; Validate OCID using Pydantic class"""
    logger.debug("Received oci_list_bucket_objects - auth_profile: %s; bucket_name: %s", auth_profile, bucket_name)
    oci_config = await oci_get(auth_profile=auth_profile)
    objects = util_oci.get_bucket_objects(bucket_name, oci_config)
    return objects


@auth.patch(
    "/{auth_profile}",
    description="Update, Test, Set as Default OCI Configuration",
    response_model=schema.OracleCloudSettings,
)
async def oci_profile_update(
    auth_profile: schema.OCIProfileType, payload: schema.OracleCloudSettings
) -> schema.OracleCloudSettings:
    """Update OCI Configuration"""
    logger.debug("Received oci_update - auth_profile: %s; payload %s", auth_profile, payload)
    try:
        namespace = util_oci.get_namespace(payload)
    except util_oci.OciException as ex:
        raise HTTPException(status_code=401, detail=f"OCI: {str(ex)}.") from ex

    oci_config = await oci_get(auth_profile=auth_profile)
    try:
        oci_config.namespace = namespace
        oci_config.tenancy = payload.tenancy if payload.tenancy else oci_config.tenancy
        oci_config.region = payload.region if payload.region else oci_config.region
        oci_config.user = payload.user if payload.user else oci_config.user
        oci_config.fingerprint = payload.fingerprint if payload.fingerprint else oci_config.fingerprint
        oci_config.key_file = payload.key_file if payload.key_file else oci_config.key_file
        oci_config.security_token_file = (
            payload.security_token_file if payload.security_token_file else oci_config.security_token_file
        )
    except AttributeError as ex:
        raise HTTPException(status_code=400, detail="OCI: Invalid Payload.") from ex

    # OCI GenAI
    try:
        oci_config.service_endpoint = (
            payload.service_endpoint if payload.service_endpoint else oci_config.service_endpoint
        )
        oci_config.compartment_id = payload.compartment_id if payload.compartment_id else oci_config.compartment_id
        if oci_config.service_endpoint != "" and oci_config.compartment_id != "":
            model_objects = models.get_model()
            for model in model_objects:
                if "OCI" in model.api:
                    model.enabled = True
                    model.url = oci_config.service_endpoint
    except AttributeError:
        pass
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
    temp_directory = embed.get_temp_directory(client, "embedding")
    for object_name in request:
        util_oci.get_object(temp_directory, object_name, bucket_name, oci_config)

    downloaded_files = [f.name for f in temp_directory.iterdir() if f.is_file()]
    return JSONResponse(status_code=200, content=downloaded_files)
