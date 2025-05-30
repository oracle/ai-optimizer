"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker:ignore selectai

import os
import server.utils.databases as databases
import server.utils.embedding as embedding
import server.utils.selectai as selectai
from common.schema import Database
import common.logging_config as logging_config

logger = logging_config.logging.getLogger("server.bootstrap.database_def")


def main() -> list[Database]:
    """Define Default Database"""
    database_list = [
        {
            "name": "DEFAULT",
            "user": os.environ.get("DB_USERNAME", default=None),
            "password": os.environ.get("DB_PASSWORD", default=None),
            "dsn": os.environ.get("DB_DSN", default=None),
            "wallet_password": os.environ.get("DB_WALLET_PASSWORD", default=None),
            "config_dir": os.environ.get("TNS_ADMIN", default="tns_admin"),
        },
    ]
    if database_list[0]["wallet_password"]:
        logger.info("Setting WALLET_LOCATION: %s", database_list[0]["config_dir"])
        database_list[0]["wallet_location"] = database_list[0]["config_dir"]

    # Check for Duplicates
    unique_entries = set()
    for db in database_list:
        if db["name"] in unique_entries:
            raise ValueError(f"Database '{db['name']}' already exists.")
        unique_entries.add(db["name"])

    # Validate Configuration and set vector_stores/status
    database_objects = []
    for database_obj in database_list:
        db = Database(**database_obj)
        database_objects.append(db)
        try:
            conn = databases.connect(db)
            db.connected = True
        except databases.DbException:
            db.connected = False
            continue
        db.vector_stores = embedding.get_vs(conn)
        db.selectai = selectai.enabled(conn)
        if db.selectai:
            db.selectai_profiles = selectai.get_profiles(conn)
        if not db.connection and len(database_objects) > 1:
            db.set_connection = databases.disconnect(conn)
        else:
            db.set_connection(conn)

    return database_objects


if __name__ == "__main__":
    main()
