"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for OCI endpoint.
"""
# spell-checker: disable

from unittest.mock import AsyncMock, patch

import pytest

from server.app.core.settings import settings
from server.app.models.schemas import ModelConfig
from server.app.oci.schemas import OciSensitive
from server.tests.conftest import assert_no_sensitive_keys, make_test_oci_profile

MOCK_CHECK = "server.app.api.v1.endpoints.oci._check_usable"
MOCK_GET_GENAI = "server.app.api.v1.endpoints.oci._get_genai_models"
MOCK_CREATE_GENAI = "server.app.api.v1.endpoints.oci._create_genai_models"

SENSITIVE_KEYS = set(OciSensitive.model_fields.keys())


@pytest.fixture(autouse=True)
def _populate_configs():
    """Inject test OciProfileConfig entries into settings."""
    original = settings.oci_configs
    settings.oci_configs = [
        make_test_oci_profile(),
        make_test_oci_profile(
            auth_profile="DEV",
            fingerprint="dd:ee:ff",
            key_content="dev-key-data",
            key_file=None,
            pass_phrase=None,
            security_token_file=None,
            tenancy="ocid1.tenancy.oc1..dev",
        ),
    ]
    yield
    settings.oci_configs = original


@pytest.fixture(autouse=True)
def mock_persist_settings():
    """Prevent persist_settings from doing real DB I/O in every test."""
    with patch("server.app.api.v1.endpoints.oci.persist_settings", new_callable=AsyncMock) as mock_persist:
        yield mock_persist


@pytest.fixture(autouse=True)
def _reset_model_configs():
    """Reset settings.model_configs before and after each test."""
    original = settings.model_configs
    yield
    settings.model_configs = original


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_oci_profiles_no_auth(app_client):
    """OCI profiles endpoint rejects requests without API key."""
    resp = await app_client.get("/v1/oci")
    assert resp.status_code == 403


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_oci_profiles(app_client, auth_headers):
    """Default response returns all configs without sensitive fields."""
    resp = await app_client.get("/v1/oci", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert_no_sensitive_keys(body, SENSITIVE_KEYS, "auth_profile")


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_oci_profiles_uses_standard_projection(app_client, auth_headers):
    """The list endpoint uses the standard projection when extra params are present."""
    resp = await app_client.get("/v1/oci", params={"include_sensitive": "true"}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert_no_sensitive_keys(body, SENSITIVE_KEYS, "auth_profile")


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_oci_profile(app_client, auth_headers):
    """Fetch a single OCI profile config by auth_profile."""
    resp = await app_client.get("/v1/oci/TEST", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_profile"] == "TEST"
    for key in SENSITIVE_KEYS:
        assert key not in body


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_oci_profile_not_found(app_client, auth_headers):
    """Return 404 for unknown auth_profile."""
    resp = await app_client.get("/v1/oci/MISSING", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.anyio
async def test_get_oci_profile_case_insensitive(app_client, auth_headers):
    """auth_profile lookup is case-insensitive."""
    resp = await app_client.get("/v1/oci/test", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["auth_profile"] == "TEST"


# --- POST /oci-profiles ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_oci_profile(app_client, auth_headers):
    """POST new auth_profile returns 201 and config appears in list."""
    with patch(MOCK_CHECK, return_value=None):
        resp = await app_client.post(
            "/v1/oci",
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
    list_resp = await app_client.get("/v1/oci", headers=auth_headers)
    profiles = [p["auth_profile"] for p in list_resp.json()]
    assert "NEW_PROFILE" in profiles


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_oci_profile_duplicate(app_client, auth_headers):
    """POST existing auth_profile returns 409."""
    resp = await app_client.post(
        "/v1/oci",
        json={"auth_profile": "TEST"},
        headers=auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_oci_profile_duplicate_case_insensitive(app_client, auth_headers):
    """POST 'test' when 'TEST' exists returns 409."""
    resp = await app_client.post(
        "/v1/oci",
        json={"auth_profile": "test"},
        headers=auth_headers,
    )
    assert resp.status_code == 409


# --- PUT /oci-profiles/{auth_profile} ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_oci_profile(app_client, auth_headers):
    """PUT with new tenancy returns 200 and field is changed."""
    with patch(MOCK_CHECK, return_value=None):
        resp = await app_client.put(
            "/v1/oci/TEST",
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
        "/v1/oci/MISSING",
        json={"tenancy": "x"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_oci_profile_partial(app_client, auth_headers):
    """PUT only one field leaves others unchanged."""
    with patch(MOCK_CHECK, return_value=None):
        resp = await app_client.put(
            "/v1/oci/TEST",
            json={"region": "us-phoenix-1"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["region"] == "us-phoenix-1"
    assert body["tenancy"] == "ocid1.tenancy.oc1..test"  # unchanged


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_oci_profile_clears_fingerprint_on_empty_string(app_client, auth_headers):
    """Submitting an empty string for ``fingerprint`` clears it.

    ``fingerprint`` is response-masked but is a public identifier, not a
    credential value: it is intentionally outside ``SECRET_UPDATE_FIELDS``.
    A blank submit must therefore actually clear the field, not preserve it.
    Test asserts only that ``fingerprint`` is cleared; downstream effects
    on ``usable`` (an api_key-auth profile becoming unusable when the
    fingerprint is removed) belong with the existing OCI auth-validity tests.
    """
    with patch(MOCK_CHECK, return_value=None):
        resp = await app_client.put(
            "/v1/oci/TEST",
            json={"fingerprint": ""},
            headers=auth_headers,
        )
    assert resp.status_code in (200, 422)
    # Verify in-memory state regardless of HTTP status — the update is
    # applied before _check_usable runs.
    cfg = next(c for c in settings.oci_configs if c.auth_profile == "TEST")
    assert cfg.fingerprint in (None, "")


# --- _check_usable integration ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_create_oci_profile_not_usable(app_client, auth_headers):
    """POST when _check_usable fails returns 422; profile persisted with usable=False."""
    with patch(MOCK_CHECK, return_value="connection refused"):
        resp = await app_client.post(
            "/v1/oci",
            json={"auth_profile": "BAD_PROFILE", "tenancy": "ocid1.tenancy.oc1..bad"},
            headers=auth_headers,
        )
    assert resp.status_code == 422
    assert "connection refused" in resp.json()["detail"]
    # Profile still persisted
    profiles = [c.auth_profile for c in settings.oci_configs]
    assert "BAD_PROFILE" in profiles


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_previously_usable_now_fails(app_client, auth_headers):
    """PUT on usable profile that now fails returns 422 and reverts values."""
    # Mark the TEST profile as usable
    for cfg in settings.oci_configs:
        if cfg.auth_profile == "TEST":
            cfg.usable = True
            break
    with patch(MOCK_CHECK, return_value="auth failed"):
        resp = await app_client.put(
            "/v1/oci/TEST",
            json={"tenancy": "ocid1.tenancy.oc1..broken"},
            headers=auth_headers,
        )
    assert resp.status_code == 422
    assert "auth failed" in resp.json()["detail"]
    # Values reverted
    for cfg in settings.oci_configs:
        if cfg.auth_profile == "TEST":
            assert cfg.tenancy == "ocid1.tenancy.oc1..test"
            assert cfg.usable is True
            break


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_previously_unusable_still_fails(app_client, auth_headers):
    """PUT on unusable profile that still fails returns 422 but keeps new values."""
    for cfg in settings.oci_configs:
        if cfg.auth_profile == "TEST":
            cfg.usable = False
            break
    with patch(MOCK_CHECK, return_value="still broken"):
        resp = await app_client.put(
            "/v1/oci/TEST",
            json={"tenancy": "ocid1.tenancy.oc1..new_attempt"},
            headers=auth_headers,
        )
    assert resp.status_code == 422
    assert "still broken" in resp.json()["detail"]
    # Values kept (not reverted)
    for cfg in settings.oci_configs:
        if cfg.auth_profile == "TEST":
            assert cfg.tenancy == "ocid1.tenancy.oc1..new_attempt"
            assert cfg.usable is False
            break


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_previously_unusable_now_usable(app_client, auth_headers):
    """PUT on unusable profile that now succeeds returns 200."""
    for cfg in settings.oci_configs:
        if cfg.auth_profile == "TEST":
            cfg.usable = False
            break
    with patch(MOCK_CHECK, return_value=None):
        resp = await app_client.put(
            "/v1/oci/TEST",
            json={"tenancy": "ocid1.tenancy.oc1..fixed"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    assert resp.json()["tenancy"] == "ocid1.tenancy.oc1..fixed"


# --- DELETE /oci-profiles/{auth_profile} ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_oci_profile(app_client, auth_headers):
    """DELETE removes config and returns 204."""
    resp = await app_client.delete("/v1/oci/TEST", headers=auth_headers)
    assert resp.status_code == 204
    # Verify it's gone
    list_resp = await app_client.get("/v1/oci", headers=auth_headers)
    profiles = [p["auth_profile"] for p in list_resp.json()]
    assert "TEST" not in profiles


@pytest.mark.unit
@pytest.mark.anyio
async def test_delete_oci_profile_not_found(app_client, auth_headers):
    """DELETE unknown auth_profile returns 404."""
    resp = await app_client.delete("/v1/oci/MISSING", headers=auth_headers)
    assert resp.status_code == 404


# --- GET /oci/genai/{auth_profile} ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_genai_models(app_client, auth_headers):
    """GET /v1/oci/genai/{auth_profile} returns 200 with model list."""
    mock_models = [{"model_name": "cohere-chat", "region": "us-chicago-1"}]
    with patch(MOCK_GET_GENAI, return_value=mock_models):
        resp = await app_client.get("/v1/oci/genai/TEST", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == mock_models


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_genai_models_not_found(app_client, auth_headers):
    """GET /v1/oci/genai/MISSING returns 404."""
    resp = await app_client.get("/v1/oci/genai/MISSING", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_genai_models_value_error(app_client, auth_headers):
    """GET returns 400 when _get_genai_models raises ValueError."""
    with patch(MOCK_GET_GENAI, side_effect=ValueError("Missing genai_compartment_id")):
        resp = await app_client.get("/v1/oci/genai/TEST", headers=auth_headers)
    assert resp.status_code == 400
    assert "Missing genai_compartment_id" in resp.json()["detail"]


# --- POST /oci/genai/{auth_profile} ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_enable_genai_models(app_client, auth_headers):
    """POST /v1/oci/genai/{auth_profile} returns 200 with model list."""
    mock_model = ModelConfig(id="cohere-chat", type="ll", provider="oci")
    with patch(MOCK_CREATE_GENAI, new_callable=AsyncMock, return_value=[mock_model]):
        resp = await app_client.post("/v1/oci/genai/TEST", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == "cohere-chat"


@pytest.mark.unit
@pytest.mark.anyio
async def test_enable_genai_models_not_found(app_client, auth_headers):
    """POST /v1/oci/genai/MISSING returns 404."""
    resp = await app_client.post("/v1/oci/genai/MISSING", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.unit
@pytest.mark.anyio
async def test_enable_genai_models_value_error(app_client, auth_headers):
    """POST returns 400 when _create_genai_models raises ValueError."""
    with patch(MOCK_CREATE_GENAI, new_callable=AsyncMock, side_effect=ValueError("Missing genai_region")):
        resp = await app_client.post("/v1/oci/genai/TEST", headers=auth_headers)
    assert resp.status_code == 400
    assert "Missing genai_region" in resp.json()["detail"]


# --- genai_region purge tests ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_oci_profile_genai_region_change_purges_models(app_client, auth_headers):
    """PUT with changed genai_region removes OCI models from model_configs."""
    # Set up: profile with genai_region and OCI model in model_configs
    for cfg in settings.oci_configs:
        if cfg.auth_profile == "TEST":
            cfg.genai_region = "us-chicago-1"
            break
    oci_model = ModelConfig(id="old-oci-model", type="ll", provider="oci")
    non_oci_model = ModelConfig(id="openai-model", type="ll", provider="openai")
    settings.model_configs = [oci_model, non_oci_model]

    with patch(MOCK_CHECK, return_value=None):
        resp = await app_client.put(
            "/v1/oci/TEST",
            json={"genai_region": "eu-frankfurt-1"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    # OCI models purged, non-OCI models kept
    providers = [m.provider for m in settings.model_configs]
    assert "oci" not in providers
    assert "openai" in providers


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_oci_profile_same_genai_region_keeps_models(app_client, auth_headers):
    """PUT with same genai_region preserves model_configs."""
    for cfg in settings.oci_configs:
        if cfg.auth_profile == "TEST":
            cfg.genai_region = "us-chicago-1"
            break
    oci_model = ModelConfig(id="kept-oci-model", type="ll", provider="oci")
    settings.model_configs = [oci_model]

    with patch(MOCK_CHECK, return_value=None):
        resp = await app_client.put(
            "/v1/oci/TEST",
            json={"genai_region": "us-chicago-1"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    # OCI models still present
    providers = [m.provider for m in settings.model_configs]
    assert "oci" in providers


# --- persist_settings failure on _check_usable error branch ---


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_previously_usable_persist_fails_on_error(app_client, auth_headers, mock_persist_settings):
    """PUT on usable profile: _check_usable fails, persist fails → 503, fields remain reverted."""
    for cfg in settings.oci_configs:
        if cfg.auth_profile == "TEST":
            cfg.usable = True
            break
    mock_persist_settings.return_value = False
    with patch(MOCK_CHECK, return_value="auth failed"):
        resp = await app_client.put(
            "/v1/oci/TEST",
            json={"tenancy": "ocid1.tenancy.oc1..broken"},
            headers=auth_headers,
        )
    assert resp.status_code == 503
    assert "persist" in resp.json()["detail"].lower()
    # Values reverted (was_usable path already rolled back before persist)
    for cfg in settings.oci_configs:
        if cfg.auth_profile == "TEST":
            assert cfg.tenancy == "ocid1.tenancy.oc1..test"
            assert cfg.usable is True
            break


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_previously_unusable_persist_fails_on_error(app_client, auth_headers, mock_persist_settings):
    """PUT on unusable profile: _check_usable fails, persist fails → 503, fields rolled back."""
    for cfg in settings.oci_configs:
        if cfg.auth_profile == "TEST":
            cfg.usable = False
            break
    mock_persist_settings.return_value = False
    with patch(MOCK_CHECK, return_value="still broken"):
        resp = await app_client.put(
            "/v1/oci/TEST",
            json={"tenancy": "ocid1.tenancy.oc1..new_attempt"},
            headers=auth_headers,
        )
    assert resp.status_code == 503
    assert "persist" in resp.json()["detail"].lower()
    # Values rolled back (persist failure forces rollback even for !was_usable)
    for cfg in settings.oci_configs:
        if cfg.auth_profile == "TEST":
            assert cfg.tenancy == "ocid1.tenancy.oc1..test"
            break


@pytest.mark.unit
@pytest.mark.anyio
async def test_update_previously_unusable_persist_fails_on_success(app_client, auth_headers, mock_persist_settings):
    """PUT on unusable profile: _check_usable succeeds, persist fails → 503, usable still False."""
    for cfg in settings.oci_configs:
        if cfg.auth_profile == "TEST":
            cfg.usable = False
            break
    mock_persist_settings.return_value = False
    with patch(MOCK_CHECK, return_value=None):
        resp = await app_client.put(
            "/v1/oci/TEST",
            json={"tenancy": "ocid1.tenancy.oc1..new_attempt"},
            headers=auth_headers,
        )
    assert resp.status_code == 503
    assert "persist" in resp.json()["detail"].lower()
    for cfg in settings.oci_configs:
        if cfg.auth_profile == "TEST":
            assert cfg.tenancy == "ocid1.tenancy.oc1..test"
            assert cfg.usable is False
            break


# ---------------------------------------------------------------------------
# Fallback response details for bucket/compartment/object listings
# ---------------------------------------------------------------------------


_OCI_SOURCE_DETAIL_TOKENS = ("marker-alpha", "marker-beta", "marker-gamma")


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_compartments_error_returns_fallback_detail(app_client, auth_headers):
    """get_compartments errors return the configured fallback detail."""
    raised = RuntimeError("marker-alpha marker-beta marker-gamma")
    with patch(
        "server.app.api.v1.endpoints.oci.get_compartments",
        side_effect=raised,
    ):
        resp = await app_client.get("/v1/oci/compartments/TEST", headers=auth_headers)
    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert detail
    for token in _OCI_SOURCE_DETAIL_TOKENS:
        assert token not in detail


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_buckets_error_returns_fallback_detail(app_client, auth_headers):
    """get_buckets errors return the configured fallback detail."""
    raised = RuntimeError("marker-alpha marker-beta marker-gamma")
    with patch(
        "server.app.api.v1.endpoints.oci.get_buckets",
        side_effect=raised,
    ):
        resp = await app_client.get(
            "/v1/oci/buckets/COMPARTMENT_TEST/TEST",
            headers=auth_headers,
        )
    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert detail
    for token in _OCI_SOURCE_DETAIL_TOKENS:
        assert token not in detail


@pytest.mark.unit
@pytest.mark.anyio
async def test_list_bucket_objects_error_returns_fallback_detail(app_client, auth_headers):
    """get_bucket_object_names errors return the configured fallback detail."""
    raised = RuntimeError("marker-alpha marker-beta marker-gamma")
    with patch(
        "server.app.api.v1.endpoints.oci.get_bucket_object_names",
        side_effect=raised,
    ):
        resp = await app_client.get("/v1/oci/objects/my-bucket/TEST", headers=auth_headers)
    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert detail
    for token in _OCI_SOURCE_DETAIL_TOKENS:
        assert token not in detail
