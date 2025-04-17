"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Default Logging Configuration
"""
# spell-checker:ignore levelname, inotify, openai, httpcore

import logging
import os

logging_level = os.environ.get("LOG_LEVEL", default=logging.INFO)

logging.basicConfig(
    level=logging_level,
    format="%(asctime)s - %(levelname)-8s - (%(name)s): %(message)s",
    datefmt="%Y-%b-%d %H:%M:%S",
    handlers=[
        # logging.FileHandler("ai-optimizer.log"),
        logging.StreamHandler()
    ],
)
logger_watchdog = logging.getLogger("watchdog.observers.inotify_buffer")
logger_watchdog.setLevel(logging.INFO)

# Ensure logging is at the desired level (override as required)
logging.getLogger("PIL").setLevel(logging.INFO)
logging.getLogger("fsevents").setLevel(logging.INFO)
logging.getLogger("numba").setLevel(logging.INFO)
logging.getLogger("oci").setLevel(logging_level)
logging.getLogger("openai").setLevel(logging_level)
logging.getLogger("httpcore").setLevel(logging_level)
logging.getLogger("uvicorn").setLevel(logging_level)
# Sagemaker continuously complains about config, suppress
logging.getLogger("sagemaker.config").setLevel(logging.WARNING)
