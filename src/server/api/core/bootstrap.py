"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore genai

from server.bootstrap import databases, models, oci, prompts, settings
import server.api.utils.oci as util_oci
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("api.core.bootstrap")

DATABASE_OBJECTS = databases.main()
OCI_OBJECTS = oci.main()
MODEL_OBJECTS = models.main()
PROMPT_OBJECTS = prompts.main()
SETTINGS_OBJECTS = settings.main()

# Attempt to load OCI GenAI Models after OCI and MODELs are Bootstrapped
try:
    oci_config = [o for o in OCI_OBJECTS if o.auth_profile == "DEFAULT"]
    if oci_config:
        util_oci.create_genai_models(oci_config[0])
except util_oci.OciException as ex:
    logger.info("Unable to bootstrap OCI GenAI Models: %s", str(ex))
