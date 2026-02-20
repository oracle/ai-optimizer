"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

OCI configuration dataclasses and config file parser.
"""
# spell-checker: ignore genai

import configparser
import logging
import os
from typing import Optional

import oci.config

from .schemas import OciProfileConfig

LOGGER = logging.getLogger(__name__)


def _get_config_file_path() -> str:
    """Return the OCI config file path from env or SDK default."""
    return os.environ.get('OCI_CLI_CONFIG_FILE', oci.config.DEFAULT_LOCATION)


def _read_key_file(key_file_path: Optional[str]) -> Optional[str]:
    """Read PEM key file contents, returning None on failure."""
    if not key_file_path:
        return None
    expanded = os.path.expanduser(key_file_path)
    try:
        with open(expanded, 'r', encoding='utf-8') as f:
            return f.read()
    except OSError as exc:
        LOGGER.warning('Cannot read key_file %s: %s', expanded, exc)
        return None


def _profile_from_oci_config(profile_name: str, file_location: str) -> OciProfileConfig:
    """Build an OCIProfileSettings from an oci.config.from_file() result."""
    config = oci.config.from_file(file_location=file_location, profile_name=profile_name)

    key_file = config.get('key_file')
    key_contents = _read_key_file(key_file)

    return OciProfileConfig(
        auth_profile=profile_name,
        user=config.get('user'),
        authentication=config.get('authentication', 'api_key'),
        security_token_file=config.get('security_token_file'),
        fingerprint=config.get('fingerprint'),
        tenancy=config.get('tenancy'),
        key=key_contents,
        pass_phrase=config.get('pass_phrase'),
        region=config.get('region'),
    )


def parse_oci_config_file(file_location: Optional[str] = None) -> list[OciProfileConfig]:
    """Parse all profiles from an OCI config file.

    Uses configparser to enumerate sections (including DEFAULT), then
    oci.config.from_file() per profile for proper inheritance.

    Returns a list of settings; profiles that fail to parse are skipped
    with a warning log.
    """
    if file_location is None:
        file_location = _get_config_file_path()

    expanded = os.path.expanduser(file_location)
    if not os.path.isfile(expanded):
        LOGGER.info('OCI config file not found: %s', expanded)
        return []

    parser = configparser.ConfigParser()
    parser.read(expanded)

    profile_names = ['DEFAULT'] + parser.sections()

    results: list[OciProfileConfig] = []
    for name in profile_names:
        try:
            settings = _profile_from_oci_config(name, file_location)
            results.append(settings)
        except (configparser.Error, oci.config.InvalidConfig, OSError, ValueError) as exc:
            LOGGER.warning("Failed to parse OCI profile '%s': %s", name, exc)

    return results
