"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Server package initialization and logging configuration.
"""

import warnings

from logging_config import configure_logging
from server.app.core.settings import settings

# Suppress cosmetic RequestsDependencyWarning from requests (chardet >= 6, charset-normalizer >= 4)
warnings.filterwarnings("ignore", message=r"urllib3.*chardet.*doesn't match a supported version")


configure_logging(settings.log_level)
