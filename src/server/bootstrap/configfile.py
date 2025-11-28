"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore configfile

import json
from pathlib import Path
from threading import Lock

from common.schema import Configuration
from common import logging_config

logger = logging_config.logging.getLogger("bootstrap.configfile")


class ConfigStore:
    """Store the Contents of the configfile"""

    _config = None
    _lock = Lock()

    @classmethod
    def load_from_file(cls, config_path: Path):
        """Load Configuration file"""
        if not config_path.exists():
            logger.warning("Config file %s does not exist. Using empty config.", config_path)
            return  # leave _config as None

        if config_path.suffix != ".json":
            logger.warning("Config file %s should be a .json file", config_path)

        with cls._lock:
            if cls._config is not None:
                return  # already loaded

            with open(config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
            cls._config = Configuration(**config_data)
            logger.info("Loaded Configuration file.")
            #logger.debug("Loaded Configuration: %s", cls._config)

    @classmethod
    def get(cls):
        """Return the configuration stored in memory"""
        return cls._config

    @classmethod
    def reset(cls):
        """Reset the configuration state. Used for testing."""
        with cls._lock:
            cls._config = None


def config_file_path() -> str:
    """Return the path where settings should be stored."""
    script_dir = Path(__file__).resolve().parent.parent
    config_file = str(script_dir / "etc" / "configuration.json")
    logger.debug("Config File path: %s", config_file)
    return config_file
