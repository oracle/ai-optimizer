"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore ollama, minilm, pplx, thenlper, mxbai, nomic, genai

import os
import configparser
import oci
import server.utils.oci as server_oci

import common.logging_config as logging_config
from common.schema import OracleCloudSettings

logger = logging_config.logging.getLogger("server.bootstrap.oci_def")


def main() -> list[OracleCloudSettings]:
    """Read in OCI Configuration options into an object"""
    config = []
    try:
        file = os.path.expanduser(os.environ.get("OCI_CLI_CONFIG_FILE", default=oci.config.DEFAULT_LOCATION))
        logger.debug("Using oci config file: %s", file)
        config_parser = configparser.ConfigParser()
        config_parser.read(file)
        for section in config_parser.sections() + ["DEFAULT"]:
            logger.debug("Evaluating OCI Profile: %s", section)
            try:
                profile_data = oci.config.from_file(file_location=file, profile_name=section)
            except oci.exceptions.InvalidKeyFilePath:
                continue
            profile_data["auth_profile"] = section
            config.append(profile_data)
    except oci.exceptions.ConfigFileNotFound:
        pass

    # If no default profile was found, append one
    if not any(item["auth_profile"] == oci.config.DEFAULT_PROFILE for item in config):
        logger.debug("Inserting empty OCI Profile: %s", oci.config.DEFAULT_PROFILE)
        config.append({"auth_profile": oci.config.DEFAULT_PROFILE})

    # override the default profile with EnvVars if set
    for default in config:
        if default["auth_profile"] == oci.config.DEFAULT_PROFILE:
            logger.debug("Overriding OCI Profile: %s with OS Environment", oci.config.DEFAULT_PROFILE)
            default["tenancy"] = os.environ.get("OCI_CLI_TENANCY", default.get("tenancy", None))
            default["region"] = os.environ.get("OCI_CLI_REGION", default.get("region", None))
            default["user"] = os.environ.get("OCI_CLI_USER", default.get("user", None))
            default["fingerprint"] = os.environ.get("OCI_CLI_FINGERPRINT", default.get("fingerprint", None))
            default["key_file"] = os.environ.get("OCI_CLI_KEY_FILE", default.get("key_file", None))
            default["security_token_file"] = os.environ.get(
                "OCI_CLI_SECURITY_TOKEN_FILE", default.get("security_token_file", None)
            )
            # Authentication Method
            default["authentication"] = os.environ.get("OCI_CLI_AUTH") or (
                "security_token" if default["security_token_file"] else "api_key"
            )
            # GenAI
            default["compartment_id"] = os.environ.get("OCI_GENAI_COMPARTMENT_ID", default.get("compartment_id", ""))
            default["service_endpoint"] = os.environ.get(
                "OCI_GENAI_SERVICE_ENDPOINT", default.get("service_endpoint", "")
            )
            # Misc
            default["log_requests"] = default.get("log_requests", False)
            default["additional_user_agent"] = default.get("additional_user_agent", "")
            default["pass_phrase"] = default.get("pass_phrase", None)

    oci_objects = []
    for oci_object in config:
        oci_config = OracleCloudSettings(**oci_object)
        oci_objects.append(oci_config)
        if oci_config.auth_profile == "DEFAULT":
            try:
                oci_config.namespace = server_oci.get_namespace(oci_config)
            except server_oci.OciException:
                continue

    logger.debug("Bootstrapped OCI Objects: %s", oci_objects)
    return oci_objects


if __name__ == "__main__":
    main()
