"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Live tests for ``src/server/app/api/v1/endpoints/oci.py``.

Drives the OCI endpoints against a real OCI tenancy using credentials from
``~/.oci/config`` (DEFAULT profile by default; override with
``OCI_CLI_PROFILE``) plus ``AIO_GENAI_COMPARTMENT_ID`` and
``AIO_GENAI_REGION``. Verifies that profile CRUD, compartment listing,
and the GenAI discovery / enable endpoints all work end-to-end.

``persist_settings`` is mocked because these tests target OCI integration,
not DB persistence — in-memory ``settings.oci_configs`` is enough to chain
the endpoint calls.
"""

import os

import pytest

pytestmark = [pytest.mark.live_oci, pytest.mark.integration]


async def test_create_and_get_oci_profile(app_client, auth_headers, live_oci_profile):
    """``POST /v1/oci`` (in fixture) created a usable profile; ``GET`` returns it."""
    response = await app_client.get(f"/v1/oci/{live_oci_profile}", headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["auth_profile"] == live_oci_profile
    # ``_check_usable`` is real here — a usable profile means OCI auth/region
    # validation passed against the live API.
    assert body.get("usable") is True


async def test_list_oci_profiles_includes_live_profile(app_client, auth_headers, live_oci_profile):
    """``GET /v1/oci`` returns the freshly created profile."""
    response = await app_client.get("/v1/oci", headers=auth_headers)
    assert response.status_code == 200, response.text
    profiles = response.json()
    names = [p["auth_profile"] for p in profiles]
    assert live_oci_profile in names


async def test_list_oci_compartments(app_client, auth_headers, live_oci_profile):
    """``GET /v1/oci/compartments/{profile}`` returns a non-empty compartment map.

    Validates OCI IAM connectivity using the live profile's credentials.
    """
    response = await app_client.get(f"/v1/oci/compartments/{live_oci_profile}", headers=auth_headers)
    assert response.status_code == 200, response.text
    compartments = response.json()
    assert isinstance(compartments, dict)
    assert compartments, "compartment listing returned an empty dict"


async def test_list_genai_models_returns_real_models(app_client, auth_headers, live_oci_genai_models):
    """``GET /v1/oci/genai/{profile}`` returns the raw OCI GenAI listing.

    Entries follow OCI's API shape: ``id`` (OCID), ``model_name``
    (human-readable, e.g. ``openai.gpt-oss-120b``), ``vendor``,
    ``capabilities`` (e.g. ``["CHAT"]`` / ``["EMBED"]``), ``region``,
    ``compartment_id``. The listing spans every subscribed region — so the
    same ``model_name`` typically appears multiple times.
    """
    assert isinstance(live_oci_genai_models, list)
    assert live_oci_genai_models, "OCI returned no GenAI models for this compartment/region"
    for m in live_oci_genai_models:
        assert "id" in m, f"model entry missing id: {m}"
        assert "model_name" in m, f"model entry missing model_name: {m}"
        assert "capabilities" in m, f"model entry missing capabilities: {m}"
        assert "region" in m, f"model entry missing region: {m}"


async def test_genai_listing_contains_openai_lineup_in_configured_region(
    app_client, auth_headers, live_oci_genai_models
):
    """The configured region exposes at least one OpenAI-family CHAT model.

    OCI's documented OpenAI lineup per
    docs.oracle.com/en-us/iaas/Content/generative-ai/model-endpoint-regions.htm
    is ``openai.gpt-oss-120b`` / ``openai.gpt-oss-20b`` — both CHAT-capable.
    If this test fails (zero OpenAI models in the configured region), the
    reasoning-completion tests will skip; surfacing it here makes the cause
    obvious instead of leaving it as an unexplained skip.
    """
    configured_region = os.environ["AIO_GENAI_REGION"]
    openai_in_region = sorted({
        m["model_name"]
        for m in live_oci_genai_models
        if (m.get("vendor") or "").lower() == "openai" and m.get("region") == configured_region
    })
    assert openai_in_region, (
        f"no OpenAI-family models in {configured_region} — check the AIO_GENAI_REGION "
        f"matches OCI's documented hosting regions"
    )
    # Every returned entry must be CHAT-capable, otherwise the reasoning tests
    # would parametrize over EMBED-only entries and fail confusingly.
    for model_name in openai_in_region:
        capabilities_seen = [
            m.get("capabilities")
            for m in live_oci_genai_models
            if m.get("model_name") == model_name and m.get("region") == configured_region
        ]
        assert any(
            "CHAT" in (caps or []) for caps in capabilities_seen
        ), f"{model_name} is OpenAI-vendor in {configured_region} but has no CHAT capability"


async def test_enable_genai_models(app_client, auth_headers, live_oci_profile):
    """``POST /v1/oci/genai/{profile}`` enables the discovered models.

    Validates the create_genai_models path end-to-end including
    ``check_single_model`` (which connectivity-tests each model via LiteLLM).
    """
    response = await app_client.post(f"/v1/oci/genai/{live_oci_profile}", headers=auth_headers)
    assert response.status_code == 200, response.text
    enabled = response.json()
    assert isinstance(enabled, list)
    assert enabled, "enable_genai_models returned an empty list"
    for m in enabled:
        assert "id" in m
        assert m.get("provider") == "oci"
