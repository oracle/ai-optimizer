"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore genai ocids

from typing import Optional, Union

from server.api.core import bootstrap, settings
from common.schema import OracleCloudSettings, ClientIdType, OCIProfileType
from common import logging_config

logger = logging_config.logging.getLogger("api.core.oci")


#####################################################
# Functions
#####################################################
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
    logger.debug("Getting OCI config for client: %s; auth_profile: %s", client, auth_profile)
    if client is not None and auth_profile is not None:
        raise ValueError("provide either 'client' or 'auth_profile', not both")

    oci_objects = bootstrap.OCI_OBJECTS
    if client is not None:
        client_settings = settings.get_client_settings(client)
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
