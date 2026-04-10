"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

OCI configuration dataclasses and config file parser.
"""
# spell-checker: ignore genai

import configparser
import logging
import os
from collections.abc import Mapping
from typing import Optional, cast, get_args

import oci.config
import oci.object_storage

from .client import init_client
from .schemas import OciAuthType, OciProfileConfig

LOGGER = logging.getLogger(__name__)


def _get_config_file_path() -> str:
    """Return the OCI config file path from env or SDK default."""
    return os.environ.get("OCI_CLI_CONFIG_FILE", oci.config.DEFAULT_LOCATION)


def _profile_from_section(profile_name: str, section: Mapping[str, str]) -> OciProfileConfig:
    """Build an OciProfileConfig from a raw configparser section dict."""
    key_file = section.get("key_file")
    if key_file:
        key_file = os.path.expanduser(key_file)
    key_content = section.get("key_content")
    raw_auth = section.get("authentication", "api_key").strip().lower()
    authentication: OciAuthType = cast(OciAuthType, raw_auth) if raw_auth in get_args(OciAuthType) else "api_key"

    return OciProfileConfig(
        auth_profile=profile_name,
        user=section.get("user"),
        authentication=authentication,
        security_token_file=section.get("security_token_file"),
        fingerprint=section.get("fingerprint"),
        tenancy=section.get("tenancy"),
        key_file=key_file,
        key_content=None if key_file else key_content,
        pass_phrase=section.get("pass_phrase"),
        region=section.get("region"),
        genai_compartment_id=section.get("genai_compartment_id"),
        genai_region=section.get("genai_region"),
    )


def _check_usable(profile: OciProfileConfig) -> Optional[str]:
    """Test OCI connectivity via get_namespace(); sets profile.usable.

    Returns None on success, or the error message on failure.
    """
    try:
        client = init_client(
            oci.object_storage.ObjectStorageClient,
            profile,
            timeout=(1, 10),
        )
        resp = client.get_namespace()
        profile.namespace = resp.data if resp else None
        profile.usable = True
        LOGGER.debug("OCI profile '%s' is usable", profile.auth_profile)
        return None
    except Exception as exc:
        LOGGER.warning("OCI profile '%s' not usable: %s", profile.auth_profile, exc)
        profile.usable = False
        return str(exc)


def parse_oci_config_file(file_location: Optional[str] = None) -> list[OciProfileConfig]:
    """Parse all profiles from an OCI config file.

    Reads raw values via configparser so that profiles with invalid key
    paths or other issues still load (as unusable).  The OCI SDK
    validation happens later in _check_usable().

    Returns a list of settings; profiles that fail to parse are skipped
    with a warning log.
    """
    if file_location is None:
        file_location = _get_config_file_path()

    expanded = os.path.expanduser(file_location)
    if not os.path.isfile(expanded):
        LOGGER.info("OCI config file not found: %s", expanded)
        return []

    parser = configparser.ConfigParser()
    parser.read(expanded)

    results: list[OciProfileConfig] = []

    # DEFAULT section (configparser stores defaults separately)
    defaults = parser.defaults()
    if defaults:
        try:
            results.append(_profile_from_section("DEFAULT", defaults))
        except Exception as exc:
            LOGGER.warning("Failed to parse OCI profile 'DEFAULT': %s", exc)

    # Named sections (inherit DEFAULT values via configparser)
    for name in parser.sections():
        try:
            section = dict(parser.items(name))
            results.append(_profile_from_section(name, section))
        except Exception as exc:
            LOGGER.warning("Failed to parse OCI profile '%s': %s", name, exc)

    return results
