"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration-test conftest.

Loads ``.env.pytest`` from the repo root (if it exists) and auto-skips
``live_oci``-marked tests when the required OCI env is not configured.
Shell env wins over the file (``override=False``), so CI can pass creds
via environment without editing.

Provides fixtures that build a live OCI profile through the public
``/v1/oci`` API (so the tests exercise the endpoint surface, not just
LiteLLM directly) and discover the GenAI models OCI actually serves —
the test model list comes from the endpoint, not a hardcoded constant.
"""

import functools
import os
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from dotenv import load_dotenv

from server.app.core.settings import settings

_REPO_ROOT = Path(__file__).resolve().parents[4]
_ENV_PYTEST = _REPO_ROOT / ".env.pytest"
if _ENV_PYTEST.exists():
    load_dotenv(_ENV_PYTEST, override=False)

_LIVE_OCI_ENV = ("AIO_GENAI_COMPARTMENT_ID", "AIO_GENAI_REGION")


def pytest_collection_modifyitems(config, items):
    """Skip live_oci-marked tests when the required OCI env is missing."""
    missing = [k for k in _LIVE_OCI_ENV if not os.getenv(k)]
    if not missing:
        return
    skip = pytest.mark.skip(reason=f"live_oci tests need {missing} (in .env.pytest or shell)")
    for item in items:
        if "live_oci" in item.keywords:
            item.add_marker(skip)


@functools.lru_cache(maxsize=1)
def _oci_default_config() -> dict[str, Any]:
    """Read OCI auth from ~/.oci/config (DEFAULT profile, or $OCI_CLI_PROFILE).

    Cached for the test session — ``~/.oci/config`` does not change at runtime.
    """
    import oci  # imported lazily so the import isn't paid when tests skip

    profile_name = os.environ.get("OCI_CLI_PROFILE", "DEFAULT")
    return oci.config.from_file(profile_name=profile_name)


@pytest.fixture(autouse=True)
def _save_restore_oci_configs():
    """Snapshot/restore ``settings.oci_configs`` around each integration test.

    Mirrors the ``_ensure_model_configs`` autouse fixture in the parent
    conftest for ``settings.model_configs``. Defends against the
    ``create_oci_profile`` leak path (appends body to ``oci_configs`` before
    ``_check_usable`` runs; if a 422 raises after persistence succeeds, the
    appended profile is not rolled back) and against any pytest.fail in the
    live fixtures that bypasses the DELETE cleanup.
    """
    original = list(settings.oci_configs)
    try:
        yield
    finally:
        settings.oci_configs = original


@pytest.fixture
async def live_oci_profile(app_client, auth_headers):
    """Create a live OCI profile through ``POST /v1/oci`` and tear it down.

    Yields the profile name. OCI auth comes from ``~/.oci/config``
    (profile ``DEFAULT`` by default; override via ``OCI_CLI_PROFILE``).
    ``genai_compartment_id`` / ``genai_region`` come from ``AIO_GENAI_*``.

    ``persist_settings`` is mocked for the entire fixture lifetime — including
    the test body — because the live tests target OCI integration, not DB
    persistence. Tests that exercise endpoints which would normally persist
    (e.g. ``POST /v1/oci/genai/{profile}``) therefore do not actually write
    to the DB; that's intentional but worth knowing when reading per-test
    expectations.
    """
    try:
        config = _oci_default_config()
    except Exception as exc:
        pytest.skip(f"OCI config not readable: {exc}")

    profile_name = f"pytest-live-{uuid.uuid4().hex[:8]}"
    body = {
        "auth_profile": profile_name,
        "authentication": "api_key",
        "tenancy": config["tenancy"],
        "user": config["user"],
        "fingerprint": config["fingerprint"],
        "key_file": config["key_file"],
        "region": config["region"],
        "genai_compartment_id": os.environ["AIO_GENAI_COMPARTMENT_ID"],
        "genai_region": os.environ["AIO_GENAI_REGION"],
    }

    with patch(
        "server.app.api.v1.endpoints.oci.persist_settings",
        new_callable=AsyncMock,
        return_value=True,
    ):
        response = await app_client.post("/v1/oci", json=body, headers=auth_headers)
        if response.status_code not in (200, 201):
            pytest.fail(f"create profile failed: {response.status_code} {response.text}")

        try:
            yield profile_name
        finally:
            await app_client.delete(f"/v1/oci/{profile_name}", headers=auth_headers)


@pytest.fixture
async def live_oci_genai_models(app_client, auth_headers, live_oci_profile) -> list[dict]:
    """Return the list of OCI GenAI models discovered via ``GET /v1/oci/genai/{profile}``.

    This is what OCI actually serves across the subscribed regions — no
    hardcoded model list. Empty list is a valid outcome (tells you OCI
    exposes nothing in this compartment).
    """
    response = await app_client.get(f"/v1/oci/genai/{live_oci_profile}", headers=auth_headers)
    if response.status_code != 200:
        pytest.fail(f"list_genai_models failed: {response.status_code} {response.text}")
    return response.json()


@pytest.fixture
def live_oci_litellm_kwargs() -> dict:
    """All OCI auth + region/compartment kwargs LiteLLM's OCI provider needs.

    LiteLLM's OCI provider requires every auth field passed in via
    ``optional_params`` or ``OCI_*`` env vars — it does not read
    ``~/.oci/config`` itself. This fixture builds the full kwargs dict
    from the OCI SDK's config resolution + ``AIO_GENAI_*`` env.
    """
    try:
        config = _oci_default_config()
    except Exception as exc:
        pytest.skip(f"OCI config not readable: {exc}")
    return {
        "oci_user": config["user"],
        "oci_fingerprint": config["fingerprint"],
        "oci_tenancy": config["tenancy"],
        "oci_key_file": config["key_file"],
        "oci_compartment_id": os.environ["AIO_GENAI_COMPARTMENT_ID"],
        "oci_region": os.environ["AIO_GENAI_REGION"],
    }
