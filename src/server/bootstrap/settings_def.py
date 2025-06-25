"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

from common.schema import Settings
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("server.bootstrap.settings_def")


def main() -> list[Settings]:
    """Define example Settings Support"""
    clients = ["default", "server"]
    settings_objects = [Settings(client=client) for client in clients]
    return settings_objects


if __name__ == "__main__":
    main()
