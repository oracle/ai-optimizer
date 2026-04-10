"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for help text endpoints.
"""
# spell-checker: disable

import pytest

from server.app.core.help_text import help_dict

pytestmark = pytest.mark.anyio


@pytest.mark.unit
async def test_get_all_help_no_auth(app_client):
    """GET /v1/help without auth returns 403."""
    resp = await app_client.get("/v1/help")
    assert resp.status_code == 403


@pytest.mark.unit
async def test_get_all_help_returns_list(app_client, auth_headers):
    """GET /v1/help returns a list matching the help_dict length."""
    resp = await app_client.get("/v1/help", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == len(help_dict)


@pytest.mark.unit
async def test_get_all_help_keys_match_dict(app_client, auth_headers):
    """Returned keys match help_dict keys exactly."""
    resp = await app_client.get("/v1/help", headers=auth_headers)
    returned_keys = {entry["key"] for entry in resp.json()}
    assert returned_keys == set(help_dict.keys())


@pytest.mark.unit
async def test_get_help_valid_key(app_client, auth_headers):
    """GET /v1/help/{key} returns the expected help text."""
    resp = await app_client.get("/v1/help/temperature", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["key"] == "temperature"
    assert body["text"] == help_dict["temperature"].strip()


@pytest.mark.unit
async def test_get_help_case_insensitive(app_client, auth_headers):
    """Uppercase key is lowered in the response."""
    resp = await app_client.get("/v1/help/TEMPERATURE", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["key"] == "temperature"


@pytest.mark.unit
async def test_get_help_not_found(app_client, auth_headers):
    """GET /v1/help/{key} returns 404 for an unknown key."""
    resp = await app_client.get("/v1/help/nonexistent_key_xyz", headers=auth_headers)
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


@pytest.mark.unit
async def test_get_help_no_auth(app_client):
    """GET /v1/help/{key} without auth returns 403."""
    resp = await app_client.get("/v1/help/temperature")
    assert resp.status_code == 403
