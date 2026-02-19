"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for the database settings persistence module.
"""

from server.app.api.v1.schemas.databases import (
    ClientDatabaseSettings,
    ClientSettings,
    DatabaseConfigEntry,
    PersistedSettings,
)
from server.app.database.config import DatabaseSettings, DatabaseState, WalletConfig
from server.app.database.settings import (
    db_config_to_entry,
    entry_to_db_settings,
    registry_to_persisted,
)


class TestDbConfigToEntry:
    """db_config_to_entry conversion."""

    def test_basic_conversion(self):
        """All DatabaseSettings fields map to the corresponding entry fields."""

        db = DatabaseState(
            settings=DatabaseSettings(
                alias="TEST",
                username="user1",
                password="pass1",
                dsn="host:1521/db",
                wallet=WalletConfig(password="wp", location="/wallet"),
                config_dir="/config",
                tcp_connect_timeout=5,
            )
        )
        entry = db_config_to_entry(db)
        assert entry.alias == "TEST"
        assert entry.user == "user1"
        assert entry.password == "pass1"
        assert entry.dsn == "host:1521/db"
        assert entry.wallet_password == "wp"
        assert entry.wallet_location == "/wallet"
        assert entry.config_dir == "/config"
        assert entry.tcp_connect_timeout == 5

    def test_none_fields(self):
        """Optional fields default to None in the entry."""

        db = DatabaseState(settings=DatabaseSettings(alias="EMPTY"))
        entry = db_config_to_entry(db)
        assert entry.alias == "EMPTY"
        assert entry.user is None
        assert entry.password is None
        assert entry.dsn is None


class TestEntryAndRoundTrip:
    """entry_to_db_settings conversion and round-trip with db_config_to_entry."""

    def test_roundtrip(self):
        """Converting to entry and back preserves all credential fields."""

        original = DatabaseSettings(
            alias="RT",
            username="u",
            password="p",
            dsn="d",
            config_dir="/c",
            tcp_connect_timeout=15,
        )
        entry = db_config_to_entry(DatabaseState(settings=original))
        restored = entry_to_db_settings(entry)
        assert restored.alias == original.alias
        assert restored.username == original.username
        assert restored.password == original.password
        assert restored.dsn == original.dsn
        assert restored.config_dir == original.config_dir
        assert restored.tcp_connect_timeout == original.tcp_connect_timeout
        # Restored should have default wallet
        assert restored.wallet.password is None
        assert restored.wallet.location is None

    def test_entry_to_settings_maps_user_to_username(self):
        """The entry 'user' field maps to DatabaseSettings 'username'."""

        entry = DatabaseConfigEntry(alias="X", user="myuser")
        settings = entry_to_db_settings(entry)
        assert settings.username == "myuser"


class TestRegistryToPersisted:
    """registry_to_persisted builds correct structure."""

    def test_single_entry(self):
        """Single-entry registry produces one database_configs item."""

        registry = [DatabaseState(settings=DatabaseSettings(alias="CORE", username="u", password="p", dsn="d"))]
        persisted = registry_to_persisted(registry, "CORE")

        assert persisted.client_settings.database.alias == "CORE"
        assert len(persisted.database_configs) == 1
        assert persisted.database_configs[0].alias == "CORE"

    def test_multiple_entries(self):
        """Multi-entry registry records the active alias and all configs."""

        registry = [
            DatabaseState(settings=DatabaseSettings(alias="CORE", username="u1", password="p1", dsn="d1")),
            DatabaseState(settings=DatabaseSettings(alias="TEST", username="u2", password="p2", dsn="d2")),
        ]
        persisted = registry_to_persisted(registry, "TEST")

        assert persisted.client_settings.database.alias == "TEST"
        assert len(persisted.database_configs) == 2
        aliases = {e.alias for e in persisted.database_configs}
        assert aliases == {"CORE", "TEST"}


class TestPersistedSettingsModel:
    """PersistedSettings JSON serialization round-trip."""

    def test_json_roundtrip(self):
        """Serializing to JSON and back preserves all fields."""

        original = PersistedSettings(
            client_settings=ClientSettings(
                database=ClientDatabaseSettings(alias="TEST"),
            ),
            database_configs=[
                DatabaseConfigEntry(
                    alias="CORE",
                    user="u",
                    password="p",
                    dsn="d",
                    tcp_connect_timeout=10,
                ),
                DatabaseConfigEntry(
                    alias="TEST",
                    user="u2",
                    password="p2",
                    dsn="d2",
                    tcp_connect_timeout=5,
                ),
            ],
        )
        json_str = original.model_dump_json()
        restored = PersistedSettings.model_validate_json(json_str)

        assert restored.client_settings.database.alias == "TEST"
        assert len(restored.database_configs) == 2
        assert restored.database_configs[0].alias == "CORE"
        assert restored.database_configs[1].tcp_connect_timeout == 5

    def test_core(self):
        """Default PersistedSettings has CORE alias and no configs."""

        persisted = PersistedSettings()
        assert persisted.client_settings.database.alias == "CORE"
        assert not persisted.database_configs
