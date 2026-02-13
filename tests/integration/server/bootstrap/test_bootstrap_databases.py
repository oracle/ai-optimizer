"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for server/bootstrap/databases.py

Tests the database bootstrap process with real configuration files
and environment variables.
"""

# pylint: disable=redefined-outer-name

import os

import pytest
from shared_fixtures import (
    assert_database_list_valid,
    assert_has_default_database,
    get_database_by_name,
)

from server.bootstrap import databases as databases_module


@pytest.mark.usefixtures("reset_config_store", "clean_bootstrap_env")
class TestDatabasesBootstrapWithConfig:
    """Integration tests for database bootstrap with configuration files."""

    def test_bootstrap_returns_database_objects(self):
        """databases.main() should return list of Database objects."""
        result = databases_module.main()
        assert_database_list_valid(result)

    def test_bootstrap_creates_default_database(self):
        """databases.main() should always create DEFAULT database."""
        result = databases_module.main()
        assert_has_default_database(result)

    def test_bootstrap_with_config_file_databases(self, reset_config_store, make_config_file):
        """databases.main() should load databases from config file."""
        config_path = make_config_file(
            database_configs=[
                {
                    "name": "CONFIG_DB1",
                    "user": "config_user1",
                    "password": "config_pass1",
                    "dsn": "host1:1521/PDB1",
                },
                {
                    "name": "CONFIG_DB2",
                    "user": "config_user2",
                    "password": "config_pass2",
                    "dsn": "host2:1521/PDB2",
                },
            ],
        )

        reset_config_store.load_from_file(config_path)
        result = databases_module.main()

        db_names = [db.name for db in result]
        assert "CONFIG_DB1" in db_names
        assert "CONFIG_DB2" in db_names

    def test_bootstrap_default_from_config_overridden_by_env(self, reset_config_store, make_config_file):
        """databases.main() should override DEFAULT config values with env vars."""
        config_path = make_config_file(
            database_configs=[
                {
                    "name": "DEFAULT",
                    "user": "config_user",
                    "password": "config_pass",
                    "dsn": "config_host:1521/CFGPDB",
                },
            ],
        )

        os.environ["DB_USERNAME"] = "env_user"
        os.environ["DB_PASSWORD"] = "env_password"

        try:
            reset_config_store.load_from_file(config_path)
            result = databases_module.main()
            default_db = get_database_by_name(result, "DEFAULT")
            assert default_db.user == "env_user"
            assert default_db.password == "env_password"
            assert default_db.dsn == "config_host:1521/CFGPDB"  # DSN not in env, keep config value
        finally:
            del os.environ["DB_USERNAME"]
            del os.environ["DB_PASSWORD"]

    def test_bootstrap_raises_on_duplicate_names(self, reset_config_store, make_config_file):
        """databases.main() should raise error for duplicate database names."""
        config_path = make_config_file(
            database_configs=[
                {"name": "DUP_DB", "user": "user1", "password": "pass1", "dsn": "dsn1"},
                {"name": "dup_db", "user": "user2", "password": "pass2", "dsn": "dsn2"},
            ],
        )

        reset_config_store.load_from_file(config_path)

        with pytest.raises(ValueError, match="Duplicate database name"):
            databases_module.main()


@pytest.mark.usefixtures("reset_config_store", "clean_bootstrap_env")
class TestDatabasesBootstrapWithEnvVars:
    """Integration tests for database bootstrap with environment variables."""

    def test_bootstrap_uses_env_vars_for_default(self):
        """databases.main() should use env vars for DEFAULT when no config."""
        os.environ["DB_USERNAME"] = "env_user"
        os.environ["DB_PASSWORD"] = "env_password"
        os.environ["DB_DSN"] = "env_host:1521/ENVPDB"

        try:
            result = databases_module.main()
            default_db = get_database_by_name(result, "DEFAULT")
            assert default_db.user == "env_user"
            assert default_db.password == "env_password"
            assert default_db.dsn == "env_host:1521/ENVPDB"
        finally:
            del os.environ["DB_USERNAME"]
            del os.environ["DB_PASSWORD"]
            del os.environ["DB_DSN"]

    def test_bootstrap_wallet_password_sets_wallet_location(self):
        """databases.main() should set wallet_location when wallet_password present."""
        os.environ["DB_WALLET_PASSWORD"] = "wallet_secret"
        os.environ["TNS_ADMIN"] = "/path/to/wallet"

        try:
            result = databases_module.main()
            default_db = get_database_by_name(result, "DEFAULT")
            assert default_db.wallet_password == "wallet_secret"
            assert default_db.wallet_location == "/path/to/wallet"
            assert default_db.config_dir == "/path/to/wallet"
        finally:
            del os.environ["DB_WALLET_PASSWORD"]
            del os.environ["TNS_ADMIN"]

    def test_bootstrap_tns_admin_default(self):
        """databases.main() should use 'tns_admin' as default config_dir."""
        result = databases_module.main()
        default_db = get_database_by_name(result, "DEFAULT")
        assert default_db.config_dir == "tns_admin"


@pytest.mark.usefixtures("clean_bootstrap_env")
class TestDatabasesBootstrapPreservation:
    """Integration tests for database bootstrap preserving non-DEFAULT databases."""

    def test_bootstrap_preserves_non_default_databases(self, reset_config_store, make_config_file):
        """databases.main() should not modify non-DEFAULT databases."""
        os.environ["DB_USERNAME"] = "should_not_apply"

        config_path = make_config_file(
            database_configs=[
                {
                    "name": "CUSTOM_DB",
                    "user": "custom_user",
                    "password": "custom_pass",
                    "dsn": "custom:1521/CPDB",
                },
            ],
        )

        try:
            reset_config_store.load_from_file(config_path)
            result = databases_module.main()
            custom_db = get_database_by_name(result, "CUSTOM_DB")
            assert custom_db.user == "custom_user"
            assert custom_db.password == "custom_pass"
        finally:
            del os.environ["DB_USERNAME"]

    def test_bootstrap_creates_default_when_not_in_config(self, reset_config_store, make_config_file):
        """databases.main() should create DEFAULT from env when not in config."""
        os.environ["DB_USERNAME"] = "env_default_user"

        config_path = make_config_file(
            database_configs=[
                {"name": "OTHER_DB", "user": "other", "password": "other", "dsn": "other"},
            ],
        )

        try:
            reset_config_store.load_from_file(config_path)
            result = databases_module.main()
            assert_has_default_database(result)
            assert "OTHER_DB" in [d.name for d in result]
            default_db = get_database_by_name(result, "DEFAULT")
            assert default_db.user == "env_default_user"
        finally:
            del os.environ["DB_USERNAME"]
