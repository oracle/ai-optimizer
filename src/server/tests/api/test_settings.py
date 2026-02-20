"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for settings endpoint.
"""

# pylint: disable=duplicate-code
import pytest

from server.app.api.v1.endpoints.settings import SENSITIVE_FIELDS
from server.app.database.schemas import DatabaseConfig, DatabaseSensitive
from server.app.models.schemas import ModelConfig, ModelSensitive
from server.app.oci.schemas import OciProfileConfig, OciSensitive
from server.app.core.settings import settings


@pytest.fixture(autouse=True)
def _populate_configs():
    """Ensure settings has at least one DB, OCI, and Model config for sensitive-field tests."""
    original_db = settings.database_configs
    original_oci = settings.oci_profile_configs
    original_model = settings.model_configs
    settings.database_configs = [
        DatabaseConfig(
            alias="TEST",
            username="testuser",
            password="secret",
            wallet_password="wallet_secret",
        ),
    ]
    settings.oci_profile_configs = [
        OciProfileConfig(
            auth_profile="TEST",
            fingerprint="aa:bb:cc",
            key="private-key-data",
            key_file="/path/to/key",
            pass_phrase="passphrase",
            security_token_file="/path/to/token",
            tenancy="ocid1.tenancy.oc1..test",
        ),
    ]
    settings.model_configs = [
        ModelConfig(
            id="test-model",
            type="ll",
            provider="openai",
            api_key="sk-secret-key",
        ),
    ]
    yield
    settings.database_configs = original_db
    settings.oci_profile_configs = original_oci
    settings.model_configs = original_model


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_settings_no_auth(app_client):
    """Settings endpoint rejects requests without API key."""
    resp = await app_client.get("/v1/settings")
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_settings_excludes_sensitive(app_client, auth_headers):
    """Default response omits sensitive fields from all config sections."""
    resp = await app_client.get("/v1/settings", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()

    # Top-level api_key must be excluded
    assert "api_key" not in body

    # Database sensitive fields must be excluded
    for db_entry in body.get("database_configs", []):
        assert "password" not in db_entry
        assert "wallet_password" not in db_entry
        # Non-sensitive fields should still be present
        assert "alias" in db_entry

    # Model sensitive fields must be excluded
    for model_entry in body.get("model_configs", []):
        assert "api_key" not in model_entry
        # Non-sensitive fields should still be present
        assert "id" in model_entry

    # OCI sensitive fields must be excluded
    for oci_entry in body.get("oci_profile_configs", []):
        assert "fingerprint" not in oci_entry
        assert "key" not in oci_entry
        assert "key_file" not in oci_entry
        assert "pass_phrase" not in oci_entry
        assert "security_token_file" not in oci_entry
        # Non-sensitive fields should still be present
        assert "auth_profile" in oci_entry


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_settings_includes_sensitive(app_client, auth_headers):
    """Response includes sensitive fields when include_sensitive=true."""
    resp = await app_client.get("/v1/settings", params={"include_sensitive": "true"}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()

    # api_key should now be present
    assert "api_key" in body
    assert body["api_key"] == settings.api_key

    # Database sensitive fields should be present
    for db_entry in body.get("database_configs", []):
        assert "password" in db_entry

    # Model sensitive fields should be present
    for model_entry in body.get("model_configs", []):
        assert "api_key" in model_entry

    # OCI sensitive fields should be present
    for oci_entry in body.get("oci_profile_configs", []):
        assert "fingerprint" in oci_entry


@pytest.mark.unit
def test_sensitive_fields_derived_from_models():
    """SENSITIVE_FIELDS entries must exactly match the Pydantic model fields."""
    assert SENSITIVE_FIELDS["database_configs"]["__all__"] == set(DatabaseSensitive.model_fields.keys())
    assert SENSITIVE_FIELDS["model_configs"]["__all__"] == set(ModelSensitive.model_fields.keys())
    assert SENSITIVE_FIELDS["oci_profile_configs"]["__all__"] == set(OciSensitive.model_fields.keys())
