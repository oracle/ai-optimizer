"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/api/v1/models.py
Tests for model configuration endpoints.
"""

import json
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from server.api.v1 import models
from server.api.utils import models as utils_models


class TestModelsList:
    """Tests for the models_list endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.models.utils_models.get")
    async def test_models_list_returns_all_models(self, mock_get, make_model):
        """models_list should return all configured models."""
        model_list = [
            make_model(model_id="gpt-4", provider="openai"),
            make_model(model_id="claude-3", provider="anthropic"),
        ]
        mock_get.return_value = model_list

        result = await models.models_list()

        assert result == model_list
        mock_get.assert_called_once()

    @pytest.mark.asyncio
    @patch("server.api.v1.models.utils_models.get")
    async def test_models_list_with_type_filter(self, mock_get):
        """models_list should filter by model type when provided."""
        mock_get.return_value = []

        await models.models_list(model_type="ll")

        mock_get.assert_called_once()
        # Verify the model_type was passed (FastAPI Query wraps the value)
        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs.get("model_type") == "ll"

    @pytest.mark.asyncio
    @patch("server.api.v1.models.utils_models.get")
    async def test_models_list_with_include_disabled(self, mock_get):
        """models_list should include disabled models when requested."""
        mock_get.return_value = []

        await models.models_list(include_disabled=True)

        mock_get.assert_called_once()
        # Verify the include_disabled was passed
        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs.get("include_disabled") is True


class TestModelsSupported:
    """Tests for the models_supported endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.models.utils_models.get_supported")
    async def test_models_supported_returns_supported_list(self, mock_get_supported):
        """models_supported should return list of supported models."""
        supported_models = [
            {"provider": "openai", "models": ["gpt-4", "gpt-4o"]},
        ]
        mock_get_supported.return_value = supported_models

        result = await models.models_supported(model_provider="openai")

        assert result == supported_models
        mock_get_supported.assert_called_once()

    @pytest.mark.asyncio
    @patch("server.api.v1.models.utils_models.get_supported")
    async def test_models_supported_filters_by_type(self, mock_get_supported):
        """models_supported should filter by model type when provided."""
        mock_get_supported.return_value = []

        await models.models_supported(model_provider="openai", model_type="ll")

        mock_get_supported.assert_called_once()
        call_kwargs = mock_get_supported.call_args.kwargs
        assert call_kwargs.get("model_provider") == "openai"
        assert call_kwargs.get("model_type") == "ll"


class TestModelsGet:
    """Tests for the models_get endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.models.utils_models.get")
    async def test_models_get_returns_single_model(self, mock_get, make_model):
        """models_get should return a single model by ID."""
        model = make_model(model_id="gpt-4", provider="openai")
        mock_get.return_value = (model,)  # Returns a tuple that unpacks

        result = await models.models_get(model_provider="openai", model_id="gpt-4")

        assert result == model
        mock_get.assert_called_once_with(model_provider="openai", model_id="gpt-4")

    @pytest.mark.asyncio
    @patch("server.api.v1.models.utils_models.get")
    async def test_models_get_raises_404_when_not_found(self, mock_get):
        """models_get should raise 404 when model not found."""
        mock_get.side_effect = utils_models.UnknownModelError("Model not found")

        with pytest.raises(HTTPException) as exc_info:
            await models.models_get(model_provider="openai", model_id="nonexistent")

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    @patch("server.api.v1.models.utils_models.get")
    async def test_models_get_raises_404_on_multiple_results(self, mock_get, make_model):
        """models_get should raise 404 when multiple models match."""
        # Returning a tuple with more than 1 element causes ValueError on unpack
        mock_get.return_value = (make_model(), make_model())

        with pytest.raises(HTTPException) as exc_info:
            await models.models_get(model_provider="openai", model_id="gpt-4")

        assert exc_info.value.status_code == 404


class TestModelsUpdate:
    """Tests for the models_update endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.models.utils_models.update")
    async def test_models_update_returns_updated_model(self, mock_update, make_model):
        """models_update should return the updated model."""
        updated_model = make_model(model_id="gpt-4", provider="openai", enabled=False)
        mock_update.return_value = updated_model

        payload = make_model(model_id="gpt-4", provider="openai")
        result = await models.models_update(payload=payload)

        assert result == updated_model
        mock_update.assert_called_once_with(payload=payload)

    @pytest.mark.asyncio
    @patch("server.api.v1.models.utils_models.update")
    async def test_models_update_raises_404_when_not_found(self, mock_update, make_model):
        """models_update should raise 404 when model not found."""
        mock_update.side_effect = utils_models.UnknownModelError("Model not found")

        payload = make_model(model_id="nonexistent", provider="openai")

        with pytest.raises(HTTPException) as exc_info:
            await models.models_update(payload=payload)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    @patch("server.api.v1.models.utils_models.update")
    async def test_models_update_raises_422_on_unreachable_url(self, mock_update, make_model):
        """models_update should raise 422 when API URL is unreachable."""
        mock_update.side_effect = utils_models.URLUnreachableError("URL unreachable")

        payload = make_model(model_id="gpt-4", provider="openai")

        with pytest.raises(HTTPException) as exc_info:
            await models.models_update(payload=payload)

        assert exc_info.value.status_code == 422


class TestModelsCreate:
    """Tests for the models_create endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.models.utils_models.create")
    async def test_models_create_returns_new_model(self, mock_create, make_model):
        """models_create should return newly created model."""
        new_model = make_model(model_id="new-model", provider="openai")
        mock_create.return_value = new_model

        result = await models.models_create(payload=make_model(model_id="new-model", provider="openai"))

        assert result == new_model

    @pytest.mark.asyncio
    @patch("server.api.v1.models.utils_models.create")
    async def test_models_create_raises_409_on_duplicate(self, mock_create, make_model):
        """models_create should raise 409 when model already exists."""
        mock_create.side_effect = utils_models.ExistsModelError("Model already exists")

        with pytest.raises(HTTPException) as exc_info:
            await models.models_create(payload=make_model())

        assert exc_info.value.status_code == 409


class TestModelsDelete:
    """Tests for the models_delete endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.models.utils_models.delete")
    async def test_models_delete_returns_200_on_success(self, mock_delete):
        """models_delete should return 200 status on success."""
        mock_delete.return_value = None

        result = await models.models_delete(model_provider="openai", model_id="gpt-4")

        assert result.status_code == 200
        mock_delete.assert_called_once_with(model_provider="openai", model_id="gpt-4")

    @pytest.mark.asyncio
    @patch("server.api.v1.models.utils_models.delete")
    async def test_models_delete_response_contains_message(self, mock_delete):
        """models_delete should return message with model name."""
        mock_delete.return_value = None

        result = await models.models_delete(model_provider="openai", model_id="gpt-4")

        body = json.loads(result.body)
        assert "openai/gpt-4" in body["message"]
