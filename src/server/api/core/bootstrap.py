"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore genai

from server.bootstrap import databases, models, oci, prompts, settings
from common import logging_config

logger = logging_config.logging.getLogger("api.core.bootstrap")

DATABASE_OBJECTS = databases.main()
MODEL_OBJECTS = models.main()
OCI_OBJECTS = oci.main()
PROMPT_OBJECTS = prompts.main()
SETTINGS_OBJECTS = settings.main()
