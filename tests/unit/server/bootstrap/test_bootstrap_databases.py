"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/bootstrap/databases.py
Tests for database bootstrap functionality.
"""

# pylint: disable=redefined-outer-name protected-access too-few-public-methods

import os

import pytest

from server.bootstrap import databases as databases_module
from tests.shared_fixtures import (
    assert_database_list_valid,
    assert_has_default_database,
    get_database_by_name,
)


@pytest.mark.usefixtures("reset_config_store", "clean_env")
class TestDatabasesMain:
    """Tests for the databases.main() function."""

    def test_main_returns_list_of_databases(self):
        """main() should return a list of Database objects."""
        result = databases_module.main()
        assert_database_list_valid(result)

    def test_main_creates_default_database_when_no_config(self):
        """main() should create DEFAULT database when no config is loaded."""
        result = databases_module.main()
        assert_has_default_database(result)

    def test_main_uses_env_vars_for_default_database(self):
        """main() should use environment variables for DEFAULT database."""
        os.environ["DB_USERNAME"] = "env_user"
        os.environ["DB_PASSWORD"] = "env_password"
        os.environ["DB_DSN"] = "env_dsn:1521/ENVPDB"
        os.environ["TNS_ADMIN"] = "/env/tns_admin"

        try:
            db_list = databases_module.main()
            default_entry = get_database_by_name(db_list, "DEFAULT")
            assert default_entry.user == "env_user"
            assert default_entry.password == "env_password"
            assert default_entry.dsn == "env_dsn:1521/ENVPDB"
            assert default_entry.config_dir == "/env/tns_admin"
        finally:
            del os.environ["DB_USERNAME"]
            del os.environ["DB_PASSWORD"]
            del os.environ["DB_DSN"]
            del os.environ["TNS_ADMIN"]

    def test_main_sets_wallet_location_when_wallet_password_present(self):
        """main() should set wallet_location when wallet_password is provided."""
        os.environ["DB_WALLET_PASSWORD"] = "wallet_pass"
        os.environ["TNS_ADMIN"] = "/wallet/path"

        try:
            result = databases_module.main()
            default_db = get_database_by_name(result, "DEFAULT")
            assert default_db.wallet_password == "wallet_pass"
            assert default_db.wallet_location == "/wallet/path"
        finally:
            del os.environ["DB_WALLET_PASSWORD"]
            del os.environ["TNS_ADMIN"]

    def test_main_with_config_file_databases(
        self, reset_config_store, temp_config_file, make_settings, make_database
    ):
        """main() should load databases from config file."""
        settings = make_settings()
        db1 = make_database(name="CONFIG_DB1", user="config_user1")
        db2 = make_database(name="CONFIG_DB2", user="config_user2")
        config_path = temp_config_file(client_settings=settings, database_configs=[db1, db2])

        try:
            reset_config_store.load_from_file(config_path)
            integration_result = databases_module.main()

            db_names = [db.name for db in integration_result]
            assert "CONFIG_DB1" in db_names
            assert "CONFIG_DB2" in db_names
        finally:
            os.unlink(config_path)

    def test_main_overrides_default_from_config_with_env_vars(
        self, reset_config_store, temp_config_file, make_settings, make_database
    ):
        """main() should override DEFAULT database from config with env vars."""
        test_settings = make_settings()
        test_db = make_database(name="DEFAULT", user="config_user", password="config_pass", dsn="config_dsn")
        cfg_path = temp_config_file(client_settings=test_settings, database_configs=[test_db])

        os.environ["DB_USERNAME"] = "env_user"
        os.environ["DB_PASSWORD"] = "env_password"

        try:
            reset_config_store.load_from_file(cfg_path)
            db_list = databases_module.main()
            default_entry = get_database_by_name(db_list, "DEFAULT")
            assert default_entry.user == "env_user"
            assert default_entry.password == "env_password"
            assert default_entry.dsn == "config_dsn"  # DSN not in env, keep config value
        finally:
            os.unlink(cfg_path)
            del os.environ["DB_USERNAME"]
            del os.environ["DB_PASSWORD"]

    def test_main_raises_on_duplicate_database_names(
        self, reset_config_store, temp_config_file, make_settings, make_database
    ):
        """main() should raise ValueError for duplicate database names."""
        settings = make_settings()
        db1 = make_database(name="DUP_DB", user="user1")
        db2 = make_database(name="dup_db", user="user2")  # Case-insensitive duplicate
        config_path = temp_config_file(client_settings=settings, database_configs=[db1, db2])

        try:
            reset_config_store.load_from_file(config_path)

            with pytest.raises(ValueError, match="Duplicate database name"):
                databases_module.main()
        finally:
            os.unlink(config_path)

    def test_main_creates_default_when_not_in_config(
        self, reset_config_store, temp_config_file, make_settings, make_database
    ):
        """main() should create DEFAULT database from env when not in config."""
        test_settings = make_settings()
        other_db = make_database(name="OTHER_DB", user="other_user")
        cfg_path = temp_config_file(client_settings=test_settings, database_configs=[other_db])

        os.environ["DB_USERNAME"] = "default_env_user"

        try:
            reset_config_store.load_from_file(cfg_path)
            db_list = databases_module.main()
            assert_has_default_database(db_list)
            assert "OTHER_DB" in [d.name for d in db_list]
            default_entry = get_database_by_name(db_list, "DEFAULT")
            assert default_entry.user == "default_env_user"
        finally:
            os.unlink(cfg_path)
            del os.environ["DB_USERNAME"]

    def test_main_handles_case_insensitive_default_name(
        self, reset_config_store, temp_config_file, make_settings, make_database
    ):
        """main() should handle DEFAULT name case-insensitively."""
        settings = make_settings()
        db = make_database(name="default", user="config_user")  # lowercase
        config_path = temp_config_file(client_settings=settings, database_configs=[db])

        os.environ["DB_USERNAME"] = "env_user"

        try:
            reset_config_store.load_from_file(config_path)
            result = databases_module.main()

            # Should find and update the lowercase "default"
            default_db = next(db for db in result if db.name.upper() == "DEFAULT")
            assert default_db.user == "env_user"
        finally:
            os.unlink(config_path)
            del os.environ["DB_USERNAME"]

    def test_main_preserves_non_default_databases_unchanged(
        self, reset_config_store, temp_config_file, make_settings, make_database
    ):
        """main() should not modify non-DEFAULT databases."""
        test_settings = make_settings()
        custom_db_config = make_database(name="CUSTOM_DB", user="custom_user", password="custom_pass")
        cfg_path = temp_config_file(client_settings=test_settings, database_configs=[custom_db_config])

        os.environ["DB_USERNAME"] = "should_not_apply"

        try:
            reset_config_store.load_from_file(cfg_path)
            db_list = databases_module.main()
            custom_entry = get_database_by_name(db_list, "CUSTOM_DB")
            assert custom_entry.user == "custom_user"
            assert custom_entry.password == "custom_pass"
        finally:
            os.unlink(cfg_path)
            del os.environ["DB_USERNAME"]

    def test_main_default_config_dir_fallback(self):
        """main() should use 'tns_admin' as default config_dir when not specified."""
        result = databases_module.main()
        default_db = get_database_by_name(result, "DEFAULT")
        assert default_db.config_dir == "tns_admin"


@pytest.mark.usefixtures("reset_config_store", "clean_env")
class TestDatabasesMainAsScript:
    """Tests for running databases module as script."""

    def test_main_callable_directly(self):
        """main() should be callable when running as script."""
        result = databases_module.main()
        assert result is not None


class TestLoggerConfiguration:
    """Tests for logger configuration."""

    def test_logger_exists(self):
        """Logger should be configured in databases module."""
        assert hasattr(databases_module, "logger")

    def test_logger_name(self):
        """Logger should have correct name."""
        assert databases_module.logger.name == "bootstrap.databases"
