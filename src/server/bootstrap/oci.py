"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore genai configfile

import os
import configparser
import oci

from server.bootstrap.configfile import ConfigStore
import server.api.utils.oci as utils_oci
import server.api.utils.models as utils_models

import common.logging_config as logging_config
from common.schema import OracleCloudSettings

logger = logging_config.logging.getLogger("bootstrap.oci")


def main() -> list[OracleCloudSettings]:
    """Read in OCI Configuration options into an object"""
    logger.debug("*** Bootstrapping OCI - Start")

    config = []

    # Load from local OCI config file
    file = os.path.expanduser(os.environ.get("OCI_CLI_CONFIG_FILE", oci.config.DEFAULT_LOCATION))

    config_parser = configparser.ConfigParser()
    try:
        config_parser.read(file)
        sections = config_parser.sections() + ["DEFAULT"]
        for section in sections:
            logger.debug("Evaluating OCI Profile: %s", section)
            try:
                profile_data = oci.config.from_file(file_location=file, profile_name=section)
            except oci.exceptions.InvalidKeyFilePath:
                continue
            profile_data["auth_profile"] = section
            config.append(profile_data)
    except oci.exceptions.ConfigFileNotFound:
        pass  # ignore if missing

    # Override DEFAULT with ConfigStore OCI configs if available
    configuration = ConfigStore.get()
    if configuration and configuration.oci_configs:
        # Convert each ConfigStore oci_config (Pydantic models) to dict
        # and replace/add matching auth_profile or append new ones
        existing_profiles = {p["auth_profile"]: p for p in config}
        for oci_conf in configuration.oci_configs:
            profile_dict = oci_conf.model_dump()  # Pydantic v2 way to dict
            profile_name = profile_dict.get("auth_profile", oci.config.DEFAULT_PROFILE)
            if profile_name in existing_profiles:
                logger.info("Overriding existing OCI profile from ConfigStore: %s", profile_name)
            else:
                logger.info("Adding new OCI profile from ConfigStore: %s", profile_name)
            existing_profiles[profile_name] = profile_dict
        config = list(existing_profiles.values())

    # Ensure DEFAULT profile exists
    if not any(item["auth_profile"] == oci.config.DEFAULT_PROFILE for item in config):
        logger.debug("Inserting empty OCI Profile: %s", oci.config.DEFAULT_PROFILE)
        config.append({"auth_profile": oci.config.DEFAULT_PROFILE})

    # Override DEFAULT profile with environment variables
    def override(profile: dict, key: str, env_key: str, env: dict, overrides: dict, default=None):
        val = env.get(env_key)
        if val is not None and val != profile.get(key):
            overrides[key] = (profile.get(key), val)
            return val
        return profile.get(key, default)

    env = os.environ

    for profile in config:
        if profile["auth_profile"] == oci.config.DEFAULT_PROFILE:
            overrides = {}

            profile.update(
                {
                    "tenancy": override(profile, "tenancy", "OCI_CLI_TENANCY", env, overrides),
                    "region": override(profile, "region", "OCI_CLI_REGION", env, overrides),
                    "user": override(profile, "user", "OCI_CLI_USER", env, overrides),
                    "fingerprint": override(profile, "fingerprint", "OCI_CLI_FINGERPRINT", env, overrides),
                    "key_file": override(profile, "key_file", "OCI_CLI_KEY_FILE", env, overrides),
                    "security_token_file": override(
                        profile, "security_token_file", "OCI_CLI_SECURITY_TOKEN_FILE", env, overrides
                    ),
                    "authentication": env.get("OCI_CLI_AUTH")
                    or ("security_token" if profile.get("security_token_file") else "api_key"),
                    "genai_compartment_id": override(
                        profile, "genai_compartment_id", "OCI_GENAI_COMPARTMENT_ID", env, overrides, None
                    ),
                    "genai_region": override(profile, "genai_region", "OCI_GENAI_REGION", env, overrides, None),
                    "log_requests": profile.get("log_requests", False),
                    "additional_user_agent": profile.get("additional_user_agent", ""),
                    "pass_phrase": profile.get("pass_phrase"),
                }
            )

            if overrides:
                logger.info("Environment variable overrides for OCI DEFAULT profile:")
                for key, (old, new) in overrides.items():
                    logger.info("  %s: '%s' -> '%s'", key, old, new)

    # Build final OracleCloudSettings objects
    oci_objects = []
    for profile_data in config:
        oci_config = OracleCloudSettings(**profile_data)
        oci_objects.append(oci_config)

        if oci_config.auth_profile == oci.config.DEFAULT_PROFILE:
            try:
                oci_config.namespace = utils_oci.get_namespace(oci_config)
            except Exception:
                logger.warning("Failed to get namespace for DEFAULT OCI profile")
                continue

    # Attempt to load OCI GenAI Models after OCI and MODELs are Bootstrapped
    try:
        oci_config = [o for o in oci_objects if o.auth_profile == "DEFAULT"]
        if oci_config:
            utils_models.create_genai(oci_config[0])
    except Exception as ex:
        logger.info("Unable to bootstrap OCI GenAI Models: %s", str(ex))

    logger.debug("*** Bootstrapping OCI - End")
    return oci_objects


if __name__ == "__main__":
    main()
