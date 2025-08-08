"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

from server.bootstrap import databases, models, oci, prompts, settings
import server.api.utils.oci as util_oci
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("api.core.bootstrap")

DATABASE_OBJECTS = databases.main()
OCI_OBJECTS = oci.main()
MODEL_OBJECTS = models.main()
PROMPT_OBJECTS = prompts.main()
SETTINGS_OBJECTS = settings.main()

# Attempt to load OCI GenAI Models
try:
    oci_config = [
        c for c in OCI_OBJECTS if c.auth_profile == "DEFAULT"
    ]
    util_oci.create_genai_models(oci_config[0])
except util_oci.OciException as ex:
    logger.info("Unable to bootstrap OCI GenAI Models: %s", str(ex))
    