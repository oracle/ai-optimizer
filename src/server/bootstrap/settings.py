"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore configfile

import logging
from server.bootstrap.configfile import ConfigStore

from common.schema import Settings


LOGGER = logging.getLogger("bootstrap.settings")


def main() -> list[Settings]:
    """Bootstrap client settings for default/server.  Replace with config file settings if provided."""
    LOGGER.debug("*** Bootstrapping Settings - Start")

    base_clients = ["default", "server"]
    settings_objects = [Settings(client=client) for client in base_clients]

    configuration = ConfigStore.get()
    if configuration and configuration.client_settings:
        LOGGER.debug("Replacing client settings with config file.")
        settings_objects = [
            configuration.client_settings.model_copy(update={"client": client}) for client in base_clients
        ]
    LOGGER.info("Created default/server client settings.")
    LOGGER.debug("*** Bootstrapping Settings - End")
    return settings_objects


if __name__ == "__main__":
    main()
