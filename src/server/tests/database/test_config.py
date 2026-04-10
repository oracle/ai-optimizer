"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for database config utilities.
"""
# spell-checker: disable

from unittest.mock import AsyncMock, MagicMock, patch

import oracledb
import pytest

from server.app.core.settings import settings
from server.app.database.config import (
    close_pool,
    create_pool,
    create_sync_connection,
    get_client_db_config,
    get_client_pool,
    get_database_settings,
    has_required_credentials,
)
from server.app.database.schemas import DatabaseConfig
from server.tests.conftest import make_core_db_config

# ---------------------------------------------------------------------------
# Unit tests (no database required)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_has_required_credentials_true():
    """has_required_credentials() returns True when all fields are set."""
    cfg = DatabaseConfig(alias="TEST", username="u", password="p", dsn="dsn")
    assert has_required_credentials(cfg)


@pytest.mark.unit
async def test_has_required_credentials_false():
    """has_required_credentials() returns False when password is missing."""
    cfg = DatabaseConfig(alias="TEST", username="u", password=None, dsn="dsn")
    assert has_required_credentials(cfg) is False


@pytest.mark.unit
async def test_get_database_settings_found():
    """get_database_settings() returns the matching config by alias."""
    cfgs = [DatabaseConfig(alias="A"), DatabaseConfig(alias="B")]
    result = get_database_settings(cfgs, "B")
    assert result is not None
    assert result.alias == "B"
    assert result is cfgs[1]


@pytest.mark.unit
async def test_get_database_settings_not_found():
    """get_database_settings() returns None when alias is missing."""
    cfgs = [DatabaseConfig(alias="A")]
    result = get_database_settings(cfgs, "MISSING")
    assert result is None


@pytest.mark.unit
async def test_close_pool_with_pool():
    """close_pool() calls pool.close() when pool is not None."""
    pool = AsyncMock()
    await close_pool(pool)
    pool.close.assert_awaited_once()


@pytest.mark.unit
async def test_close_pool_with_none():
    """close_pool() is a no-op when pool is None."""
    await close_pool(None)  # Should not raise


@pytest.mark.unit
async def test_close_pool_swallows_error():
    """close_pool() silently catches oracledb.Error."""
    pool = AsyncMock()
    pool.close = AsyncMock(side_effect=oracledb.Error("close failed"))
    await close_pool(pool)  # Should not raise
    pool.close.assert_awaited_once()


@pytest.mark.unit
async def test_create_pool_missing_credentials():
    """create_pool() raises ValueError and sets usable=False when credentials missing."""
    cfg = DatabaseConfig(alias="TEST", username="u", password=None, dsn="dsn")
    with pytest.raises(ValueError, match="missing credentials"):
        await create_pool(cfg)
    assert cfg.usable is False


@pytest.mark.unit
async def test_create_pool_strips_retry_params():
    """create_pool() strips retry_count and retry_delay from the DSN."""
    dsn = "(description=(retry_count=20)(retry_delay=3)(address=(host=db.example.com)(port=1521)))"
    expected_dsn = "(description=(address=(host=db.example.com)(port=1521)))"
    cfg = DatabaseConfig(alias="TEST", username="u", password="p", dsn=dsn)

    with patch("server.app.database.config.oracledb.create_pool_async", new_callable=MagicMock) as mock_create:
        await create_pool(cfg)

    _, kwargs = mock_create.call_args
    assert kwargs["dsn"] == expected_dsn


@pytest.mark.unit
async def test_create_pool_strips_retry_params_case_insensitive():
    """Retry param stripping is case-insensitive."""
    dsn = "(description=(RETRY_COUNT=5)(Retry_Delay=10)(address=(host=h)))"
    cfg = DatabaseConfig(alias="TEST", username="u", password="p", dsn=dsn)

    with patch("server.app.database.config.oracledb.create_pool_async", new_callable=MagicMock) as mock_create:
        await create_pool(cfg)

    _, kwargs = mock_create.call_args
    assert "retry_count" not in kwargs["dsn"].lower()
    assert "retry_delay" not in kwargs["dsn"].lower()


@pytest.mark.unit
async def test_create_pool_tcp_connect_timeout_from_config():
    """create_pool() passes tcp_connect_timeout from config."""
    cfg = DatabaseConfig(alias="TEST", username="u", password="p", dsn="dsn", tcp_connect_timeout=10)

    with patch("server.app.database.config.oracledb.create_pool_async", new_callable=MagicMock) as mock_create:
        await create_pool(cfg)

    _, kwargs = mock_create.call_args
    assert kwargs["tcp_connect_timeout"] == 10


@pytest.mark.unit
async def test_create_pool_wallet_defaults():
    """Wallet password without location defaults location to config_dir."""
    cfg = DatabaseConfig(alias="TEST", username="u", password="p", dsn="dsn", wallet_password="secret")
    cfg.config_dir = "/opt/wallet"

    with patch("server.app.database.config.oracledb.create_pool_async", new_callable=MagicMock) as mock_create:
        await create_pool(cfg)

    mock_create.assert_called_once()
    _, kwargs = mock_create.call_args
    assert kwargs["wallet_password"] == "secret"
    assert kwargs["wallet_location"] == "/opt/wallet"


@pytest.mark.unit
async def test_create_pool_wallet_location_preserved():
    """Provided wallet_location is passed through unchanged."""
    cfg = DatabaseConfig(
        alias="TEST",
        username="u",
        password="p",
        dsn="dsn",
        wallet_password="secret",
        wallet_location="/wallet/path",
    )

    with patch("server.app.database.config.oracledb.create_pool_async", new_callable=MagicMock) as mock_create:
        await create_pool(cfg)

    mock_create.assert_called_once()
    _, kwargs = mock_create.call_args
    assert kwargs["wallet_location"] == "/wallet/path"


# ---------------------------------------------------------------------------
# create_sync_connection
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_create_sync_connection_missing_credentials():
    """create_sync_connection() raises ValueError when credentials missing."""
    cfg = DatabaseConfig(alias="TEST", username="u", password=None, dsn="dsn")
    with pytest.raises(ValueError, match="missing credentials"):
        create_sync_connection(cfg)


@pytest.mark.unit
async def test_create_sync_connection_basic():
    """create_sync_connection() passes credentials to oracledb.connect."""
    cfg = DatabaseConfig(alias="TEST", username="u", password="p", dsn="dsn")

    with patch("server.app.database.config.oracledb.connect") as mock_connect:
        create_sync_connection(cfg)

    _, kwargs = mock_connect.call_args
    assert kwargs["user"] == "u"
    assert kwargs["password"] == "p"
    assert kwargs["dsn"] == "dsn"


@pytest.mark.unit
async def test_create_sync_connection_strips_retry():
    """create_sync_connection() strips retry_count and retry_delay from DSN."""
    dsn = "(description=(retry_count=20)(retry_delay=3)(address=(host=h)(port=1521)))"
    expected = "(description=(address=(host=h)(port=1521)))"
    cfg = DatabaseConfig(alias="TEST", username="u", password="p", dsn=dsn)

    with patch("server.app.database.config.oracledb.connect") as mock_connect:
        create_sync_connection(cfg)

    _, kwargs = mock_connect.call_args
    assert kwargs["dsn"] == expected


@pytest.mark.unit
async def test_create_sync_connection_wallet_defaults():
    """Wallet password without location defaults to config_dir."""
    cfg = DatabaseConfig(alias="TEST", username="u", password="p", dsn="dsn", wallet_password="secret")
    cfg.config_dir = "/opt/wallet"

    with patch("server.app.database.config.oracledb.connect") as mock_connect:
        create_sync_connection(cfg)

    _, kwargs = mock_connect.call_args
    assert kwargs["wallet_password"] == "secret"
    assert kwargs["wallet_location"] == "/opt/wallet"


# ---------------------------------------------------------------------------
# get_client_db_config / get_client_pool
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_get_client_db_config_found():
    """get_client_db_config() returns config when pool exists and is usable."""
    pool = object()
    cfg = DatabaseConfig(alias="SRC")
    cfg.pool = pool  # type: ignore[assignment]
    cfg.usable = True
    settings.database_configs = [cfg]
    settings.client_settings.database.alias = "SRC"

    result = get_client_db_config()
    assert result is cfg


@pytest.mark.unit
async def test_get_client_db_config_no_pool():
    """get_client_db_config() returns None when pool is absent."""
    cfg = DatabaseConfig(alias="SRC")
    cfg.usable = True
    settings.database_configs = [cfg]
    settings.client_settings.database.alias = "SRC"

    assert get_client_db_config() is None


@pytest.mark.unit
async def test_get_client_db_config_not_usable():
    """get_client_db_config() returns None when pool exists but usable=False."""
    pool = object()
    cfg = DatabaseConfig(alias="SRC")
    cfg.pool = pool  # type: ignore[assignment]
    cfg.usable = False
    settings.database_configs = [cfg]
    settings.client_settings.database.alias = "SRC"

    assert get_client_db_config() is None


@pytest.mark.unit
async def test_get_client_pool_found():
    """get_client_pool() returns pool when available."""
    pool = object()
    cfg = DatabaseConfig(alias="SRC")
    cfg.pool = pool  # type: ignore[assignment]
    cfg.usable = True
    settings.database_configs = [cfg]
    settings.client_settings.database.alias = "SRC"

    assert get_client_pool() is pool


@pytest.mark.unit
async def test_get_client_pool_missing():
    """get_client_pool() returns None when database unavailable."""
    settings.database_configs = []
    settings.client_settings.database.alias = "MISSING"

    assert get_client_pool() is None


# ---------------------------------------------------------------------------
# Integration tests (require Oracle container)
# ---------------------------------------------------------------------------


@pytest.mark.db
async def test_create_pool_success(configure_db_env):
    """create_pool() returns a usable pool with valid credentials."""
    del configure_db_env
    cfg = make_core_db_config()
    pool = await create_pool(cfg)
    assert pool is not None
    await pool.close()


@pytest.mark.db
async def test_close_pool_real(configure_db_env):
    """close_pool() closes a real pool without error."""
    del configure_db_env
    cfg = make_core_db_config()
    pool = await create_pool(cfg)
    assert pool is not None
    await close_pool(pool)
