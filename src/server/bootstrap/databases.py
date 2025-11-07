"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore configfile

import os
from server.bootstrap.configfile import ConfigStore

from common.schema import Database
from common import logging_config

logger = logging_config.logging.getLogger("bootstrap.databases")


def main() -> list[Database]:
    """Define Default Database"""
    logger.debug("*** Bootstrapping Database - Start")
    configuration = ConfigStore.get()
    db_configs = configuration.database_configs if configuration and configuration.database_configs else []

    # Check for Duplicates from Configfile
    seen = set()
    for db in db_configs:
        db_name_lower = db.name.lower()
        if db_name_lower in seen:
            raise ValueError(f"Duplicate database name found in config: '{db.name}'")
        seen.add(db_name_lower)

    database_objects = []
    default_found = False

    for db in db_configs:
        if db.name.upper() == "DEFAULT":
            default_found = True
            updated = db.model_copy(
                update={
                    "user": os.getenv("DB_USERNAME", db.user),
                    "password": os.getenv("DB_PASSWORD", db.password),
                    "dsn": os.getenv("DB_DSN", db.dsn),
                    "wallet_password": os.getenv("DB_WALLET_PASSWORD", db.wallet_password),
                    "config_dir": os.getenv("TNS_ADMIN", db.config_dir or "tns_admin"),
                }
            )
            if updated.wallet_password:
                updated.wallet_location = updated.config_dir
                logger.info("Setting WALLET_LOCATION: %s", updated.config_dir)
            database_objects.append(updated)
        else:
            database_objects.append(db)

    # If DEFAULT wasn't in config, create it from env vars
    if not default_found:
        data = {
            "name": "DEFAULT",
            "user": os.getenv("DB_USERNAME"),
            "password": os.getenv("DB_PASSWORD"),
            "dsn": os.getenv("DB_DSN"),
            "wallet_password": os.getenv("DB_WALLET_PASSWORD"),
            "config_dir": os.getenv("TNS_ADMIN", "tns_admin"),
        }
        if data["wallet_password"]:
            data["wallet_location"] = data["config_dir"]
            logger.info("Setting WALLET_LOCATION: %s", data["config_dir"])
        database_objects.append(Database(**data))

    logger.debug("Bootstrapped Databases: %s", database_objects)
    logger.debug("*** Bootstrapping Database - End")
    return database_objects


if __name__ == "__main__":
    main()
