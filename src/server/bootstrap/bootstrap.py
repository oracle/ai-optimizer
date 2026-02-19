"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore genai

from server.bootstrap import databases, models, oci, settings
from common import logging_config

logger = logging_config.logging.getLogger("bootstrap")

DATABASE_OBJECTS = databases.main()
MODEL_OBJECTS = models.main()
OCI_OBJECTS = oci.main()
SETTINGS_OBJECTS = settings.main()
