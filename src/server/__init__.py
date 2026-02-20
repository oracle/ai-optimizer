"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Server package initialization and logging configuration.
"""

from logging_config import configure_logging
# from server.app.core.settings import settings

# configure_logging(settings.log_level)
configure_logging()
