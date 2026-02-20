"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for OCI profiles endpoint.
"""
# pylint: disable=duplicate-code

import pytest

from server.app.oci.schemas import OciProfileConfig, OciSensitive
from server.app.core.settings import settings

SENSITIVE_KEYS = set(OciSensitive.model_fields.keys())


@pytest.fixture(autouse=True)
def _populate_configs():
    """Inject test OciProfileConfig entries into settings."""
    original = settings.oci_profile_configs
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
        OciProfileConfig(
            auth_profile="DEV",
            fingerprint="dd:ee:ff",
            key="dev-key-data",
            tenancy="ocid1.tenancy.oc1..dev",
        ),
    ]
    yield
    settings.oci_profile_configs = original


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_oci_profiles_no_auth(app_client):
    """OCI profiles endpoint rejects requests without API key."""
    resp = await app_client.get("/v1/oci-profiles")
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_oci_profiles(app_client, auth_headers):
    """Default response returns all configs without sensitive fields."""
    resp = await app_client.get("/v1/oci-profiles", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    for entry in body:
        for key in SENSITIVE_KEYS:
            assert key not in entry
        assert "auth_profile" in entry


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_oci_profiles_sensitive(app_client, auth_headers):
    """Response includes sensitive fields when include_sensitive=true."""
    resp = await app_client.get("/v1/oci-profiles", params={"include_sensitive": "true"}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[0]["fingerprint"] == "aa:bb:cc"
    assert body[0]["key"] == "private-key-data"


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_oci_profile(app_client, auth_headers):
    """Fetch a single OCI profile config by auth_profile."""
    resp = await app_client.get("/v1/oci-profiles/TEST", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_profile"] == "TEST"
    for key in SENSITIVE_KEYS:
        assert key not in body


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_oci_profile_not_found(app_client, auth_headers):
    """Return 404 for unknown auth_profile."""
    resp = await app_client.get("/v1/oci-profiles/MISSING", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_oci_profile_case_insensitive(app_client, auth_headers):
    """auth_profile lookup is case-insensitive."""
    resp = await app_client.get("/v1/oci-profiles/test", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["auth_profile"] == "TEST"


# --- POST /oci-profiles ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_oci_profile(app_client, auth_headers):
    """POST new auth_profile returns 201 and config appears in list."""
    resp = await app_client.post(
        "/v1/oci-profiles",
        json={"auth_profile": "NEW_PROFILE", "tenancy": "ocid1.tenancy.oc1..new"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["auth_profile"] == "NEW_PROFILE"
    assert body["tenancy"] == "ocid1.tenancy.oc1..new"
    for key in SENSITIVE_KEYS:
        assert key not in body
    # Verify it appears in the list
    list_resp = await app_client.get("/v1/oci-profiles", headers=auth_headers)
    profiles = [p["auth_profile"] for p in list_resp.json()]
    assert "NEW_PROFILE" in profiles


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_oci_profile_duplicate(app_client, auth_headers):
    """POST existing auth_profile returns 409."""
    resp = await app_client.post(
        "/v1/oci-profiles",
        json={"auth_profile": "TEST"},
        headers=auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_oci_profile_duplicate_case_insensitive(app_client, auth_headers):
    """POST 'test' when 'TEST' exists returns 409."""
    resp = await app_client.post(
        "/v1/oci-profiles",
        json={"auth_profile": "test"},
        headers=auth_headers,
    )
    assert resp.status_code == 409


# --- PUT /oci-profiles/{auth_profile} ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_oci_profile(app_client, auth_headers):
    """PUT with new tenancy returns 200 and field is changed."""
    resp = await app_client.put(
        "/v1/oci-profiles/TEST",
        json={"tenancy": "ocid1.tenancy.oc1..updated"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tenancy"] == "ocid1.tenancy.oc1..updated"
    for key in SENSITIVE_KEYS:
        assert key not in body


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_oci_profile_not_found(app_client, auth_headers):
    """PUT unknown auth_profile returns 404."""
    resp = await app_client.put(
        "/v1/oci-profiles/MISSING",
        json={"tenancy": "x"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_oci_profile_partial(app_client, auth_headers):
    """PUT only one field leaves others unchanged."""
    resp = await app_client.put(
        "/v1/oci-profiles/TEST",
        json={"region": "us-phoenix-1"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["region"] == "us-phoenix-1"
    assert body["tenancy"] == "ocid1.tenancy.oc1..test"  # unchanged


# --- DELETE /oci-profiles/{auth_profile} ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_oci_profile(app_client, auth_headers):
    """DELETE removes config and returns 204."""
    resp = await app_client.delete("/v1/oci-profiles/TEST", headers=auth_headers)
    assert resp.status_code == 204
    # Verify it's gone
    list_resp = await app_client.get("/v1/oci-profiles", headers=auth_headers)
    profiles = [p["auth_profile"] for p in list_resp.json()]
    assert "TEST" not in profiles


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_oci_profile_not_found(app_client, auth_headers):
    """DELETE unknown auth_profile returns 404."""
    resp = await app_client.delete("/v1/oci-profiles/MISSING", headers=auth_headers)
    assert resp.status_code == 404
