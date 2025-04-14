"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

from common.schema import Settings
import common.logging_config as logging_config
import os

logger = logging_config.logging.getLogger("server.bootstrap.settings_def")

def _settings_path() -> str:
    """Return the path where settings should be stored.

    It assumes that this module is in src/server/bootsrap and removes
    "server/bootstrap/settings_def.py" from the path.
    """
    src_dir_comps = __file__.split(os.sep)[:-3]
    src_dir_comps.extend(["etc", "settings.json"])

    return os.sep.join(src_dir_comps)


# SETTIGS_PATH is computed once the first time this module is loaded
SETTINGS_PATH = _settings_path()

def restore_or_default_settings(client: str, settings_file: str = SETTINGS_PATH) -> Settings:
    """Return a Settings instance restoring from JSON file or with default values.

    Arguments
    ---------
    client -- Client unique identifier
    settings_file -- Path to the settings file with default value, but can be injected for testing
    """
    if os.path.isfile(settings_file) and os.access(settings_file, os.R_OK):
        with open(settings_file, 'r') as file:
            settings_json = file.read()
    else:
        settings_json = ""
    return Settings.from_json(client, settings_json)


def main() -> list[Settings]:
    """Define example Settings Support"""
    clients = ["default", "server"]
    settings_objects = [restore_or_default_settings(client=client) for client in clients]
    return settings_objects


if __name__ == "__main__":
    main()
