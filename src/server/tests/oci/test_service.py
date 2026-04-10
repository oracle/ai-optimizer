"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for server.app.oci.service.
"""
# spell-checker: disable

from unittest.mock import MagicMock, patch

import pytest

from server.app.core.settings import settings
from server.app.oci.schemas import OciProfileConfig
from server.app.oci.service import create_genai_models, get_genai_models, get_regions

MODULE = "server.app.oci.service"


@pytest.fixture(autouse=True)
def _reset_model_configs():
    """Reset settings.model_configs before and after each test."""
    original = settings.model_configs
    settings.model_configs = []
    yield
    settings.model_configs = original


def _make_profile(**overrides) -> OciProfileConfig:
    """Build a test OCI profile."""
    defaults = {
        "auth_profile": "TEST",
        "genai_compartment_id": "ocid1.compartment.oc1..genai",
        "genai_region": "us-chicago-1",
        "tenancy": "ocid1.tenancy.oc1..test",
        "region": "us-phoenix-1",
    }
    return OciProfileConfig(**{**defaults, **overrides})


def _make_model_response(display_name, capabilities, deprecated=False, lifecycle_details="Base Model created"):
    """Build a mock model object as returned by OCI SDK."""
    model = MagicMock()
    model.display_name = display_name
    model.capabilities = capabilities
    model.vendor = "oracle"
    model.id = f"ocid1.generativeaimodel.oc1..{display_name}"
    model.time_deprecated = "2024-01-01" if deprecated else None
    model.time_dedicated_retired = None
    model.time_on_demand_retired = None
    model.lifecycle_details = lifecycle_details
    return model


# ---------------------------------------------------------------------------
# get_regions
# ---------------------------------------------------------------------------


class TestGetRegions:
    """Test get_regions retrieves subscribed regions."""

    def test_returns_subscribed_regions_list(self):
        """Returns a list of region dicts from the identity client."""
        profile = _make_profile()
        mock_region = MagicMock()
        mock_region.is_home_region = True
        mock_region.region_key = "PHX"
        mock_region.region_name = "us-phoenix-1"
        mock_region.status = "READY"

        mock_client = MagicMock()
        mock_client.list_region_subscriptions.return_value.data = [mock_region]

        with patch(f"{MODULE}.init_client", return_value=mock_client):
            result = get_regions(profile)

        assert len(result) == 1
        assert result[0]["region_name"] == "us-phoenix-1"
        assert result[0]["is_home_region"] is True


# ---------------------------------------------------------------------------
# get_genai_models
# ---------------------------------------------------------------------------


class TestGetGenaiModels:
    """Test get_genai_models model discovery."""

    def test_raises_value_error_when_missing_compartment_id(self):
        """Raises ValueError when genai_compartment_id is missing."""
        profile = _make_profile(genai_compartment_id=None)

        with pytest.raises(ValueError, match="Missing genai_compartment_id"):
            get_genai_models(profile)

    def test_raises_value_error_when_regional_and_missing_region(self):
        """Raises ValueError when regional=True and genai_region is missing."""
        profile = _make_profile(genai_region=None)

        with pytest.raises(ValueError, match="Missing genai_region"):
            get_genai_models(profile, regional=True)

    def test_regional_true_uses_single_region(self):
        """regional=True uses only the configured genai_region."""
        profile = _make_profile()
        model = _make_model_response("cohere-chat", ["CHAT"])

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data.items = [model]
        mock_client.list_models.return_value = mock_response

        with patch(f"{MODULE}.init_client", return_value=mock_client):
            result = get_genai_models(profile, regional=True)

        assert len(result) == 1
        assert result[0]["region"] == "us-chicago-1"

    def test_filters_deprecated_models(self):
        """Deprecated models are excluded from results."""
        profile = _make_profile()
        active_model = _make_model_response("cohere-chat", ["CHAT"])
        deprecated_model = _make_model_response("old-model", ["CHAT"], deprecated=True)

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data.items = [active_model, deprecated_model]
        mock_client.list_models.return_value = mock_response

        with patch(f"{MODULE}.init_client", return_value=mock_client):
            result = get_genai_models(profile, regional=True)

        model_names = [m["model_name"] for m in result]
        assert "cohere-chat" in model_names
        assert "old-model" not in model_names

    def test_filters_non_ready_models(self):
        """Models not yet ready for inference are excluded."""
        profile = _make_profile()
        ready_model = _make_model_response("cohere-chat", ["CHAT"])
        creating_model = _make_model_response("meta.llama-4-scout", ["CHAT"], lifecycle_details="Creating Base Model")

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data.items = [ready_model, creating_model]
        mock_client.list_models.return_value = mock_response

        with patch(f"{MODULE}.init_client", return_value=mock_client):
            result = get_genai_models(profile, regional=True)

        model_names = [m["model_name"] for m in result]
        assert "cohere-chat" in model_names
        assert "meta.llama-4-scout" not in model_names

    def test_deduplicates_models(self):
        """Duplicate models in the same region are excluded."""
        profile = _make_profile()
        model1 = _make_model_response("cohere-chat", ["CHAT"])
        model2 = _make_model_response("cohere-chat", ["CHAT"])

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.data.items = [model1, model2]
        mock_client.list_models.return_value = mock_response

        with patch(f"{MODULE}.init_client", return_value=mock_client):
            result = get_genai_models(profile, regional=True)

        assert len(result) == 1

    def test_handles_service_error_gracefully(self):
        """ServiceError in a region is caught and skipped."""
        import oci.exceptions

        profile = _make_profile()
        mock_client = MagicMock()
        mock_client.list_models.side_effect = oci.exceptions.ServiceError(
            status=400, code="InvalidParameter", headers={}, message="bad request"
        )

        with patch(f"{MODULE}.init_client", return_value=mock_client):
            result = get_genai_models(profile, regional=True)

        assert not result

    def test_handles_request_exception_gracefully(self):
        """RequestException/MaxRetryError is caught and skipped."""
        import oci.exceptions

        profile = _make_profile()
        mock_client = MagicMock()
        mock_client.list_models.side_effect = oci.exceptions.RequestException("timeout")

        with patch(f"{MODULE}.init_client", return_value=mock_client):
            result = get_genai_models(profile, regional=True)

        assert not result

    def test_handles_connect_timeout_gracefully(self):
        """ConnectTimeout is caught and skipped.

        ConnectTimeout is NOT a subclass of oci.exceptions.RequestException,
        so it must be caught explicitly.
        """
        import oci.exceptions

        profile = _make_profile()
        mock_client = MagicMock()
        mock_client.list_models.side_effect = oci.exceptions.ConnectTimeout("connect timeout=1")

        with patch(f"{MODULE}.init_client", return_value=mock_client):
            result = get_genai_models(profile, regional=True)

        assert not result


# ---------------------------------------------------------------------------
# create_genai_models
# ---------------------------------------------------------------------------


class TestCreateGenaiModels:
    """Test create_genai_models model creation."""

    @pytest.mark.anyio
    async def test_creates_chat_models_as_type_ll(self):
        """CHAT capability models are created with type='ll'."""
        profile = _make_profile()
        models = [
            {
                "region": "us-chicago-1",
                "compartment_id": "comp",
                "model_name": "cohere-chat",
                "capabilities": ["CHAT"],
                "vendor": "oracle",
                "id": "ocid1",
            }
        ]

        with (
            patch(f"{MODULE}.get_genai_models", return_value=models),
            patch(f"{MODULE}.register_model") as mock_register,
        ):
            result = await create_genai_models(profile)

        assert len(result) == 1
        assert result[0].type == "ll"
        mock_register.assert_called_once()

    @pytest.mark.anyio
    async def test_creates_text_embeddings_models_as_type_embed(self):
        """TEXT_EMBEDDINGS capability models are created with type='embed'."""
        profile = _make_profile()
        models = [
            {
                "region": "us-chicago-1",
                "compartment_id": "comp",
                "model_name": "cohere-embed",
                "capabilities": ["TEXT_EMBEDDINGS"],
                "vendor": "oracle",
                "id": "ocid2",
            }
        ]

        with (
            patch(f"{MODULE}.get_genai_models", return_value=models),
            patch(f"{MODULE}.register_model") as mock_register,
        ):
            result = await create_genai_models(profile)

        assert len(result) == 1
        assert result[0].type == "embed"
        mock_register.assert_called_once()

    @pytest.mark.anyio
    async def test_skips_models_with_other_capabilities(self):
        """Models without CHAT or TEXT_EMBEDDINGS are skipped."""
        profile = _make_profile()
        models = [
            {
                "region": "us-chicago-1",
                "compartment_id": "comp",
                "model_name": "summarize-model",
                "capabilities": ["SUMMARIZE"],
                "vendor": "oracle",
                "id": "ocid3",
            }
        ]

        with (
            patch(f"{MODULE}.get_genai_models", return_value=models),
            patch(f"{MODULE}.register_model") as mock_register,
        ):
            result = await create_genai_models(profile)

        assert len(result) == 0
        mock_register.assert_not_called()

    @pytest.mark.anyio
    async def test_purges_existing_oci_models(self):
        """Existing OCI provider models are purged before creating new ones."""
        from server.app.models.schemas import ModelConfig

        profile = _make_profile()
        # Pre-populate with an existing OCI model
        settings.model_configs = [ModelConfig(id="old-oci", type="ll", provider="oci")]

        models = [
            {
                "region": "us-chicago-1",
                "compartment_id": "comp",
                "model_name": "new-chat",
                "capabilities": ["CHAT"],
                "vendor": "oracle",
                "id": "ocid4",
            }
        ]

        with (
            patch(f"{MODULE}.get_genai_models", return_value=models),
            patch(f"{MODULE}.register_model"),
        ):
            await create_genai_models(profile)

        # The old OCI model should be purged
        old_oci = [m for m in settings.model_configs if m.id == "old-oci"]
        assert len(old_oci) == 0
