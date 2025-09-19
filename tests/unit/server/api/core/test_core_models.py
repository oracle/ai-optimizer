"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""
# spell-checker: disable

from unittest.mock import patch, MagicMock

import pytest

from server.api.core import models
from server.api.core.models import URLUnreachableError, InvalidModelError, ExistsModelError, UnknownModelError
from common.schema import Model


class TestModelsExceptions:
    """Test custom exception classes"""

    def test_url_unreachable_error(self):
        """Test URLUnreachableError exception"""
        error = URLUnreachableError("URL is unreachable")
        assert str(error) == "URL is unreachable"
        assert isinstance(error, ValueError)

    def test_invalid_model_error(self):
        """Test InvalidModelError exception"""
        error = InvalidModelError("Invalid model data")
        assert str(error) == "Invalid model data"
        assert isinstance(error, ValueError)

    def test_exists_model_error(self):
        """Test ExistsModelError exception"""
        error = ExistsModelError("Model already exists")
        assert str(error) == "Model already exists"
        assert isinstance(error, ValueError)

    def test_unknown_model_error(self):
        """Test UnknownModelError exception"""
        error = UnknownModelError("Model not found")
        assert str(error) == "Model not found"
        assert isinstance(error, ValueError)


class TestModels:
    """Test models module functionality"""

    def setup_method(self):
        """Setup test data before each test"""
        self.sample_model = Model(
            id="test-model", provider="openai", type="ll", enabled=True, api_base="https://api.openai.com"
        )
        self.disabled_model = Model(id="disabled-model", provider="anthropic", type="ll", enabled=False)

    @patch("server.api.core.models.bootstrap.MODEL_OBJECTS")
    def test_get_model_all_models(self, mock_model_objects):
        """Test getting all models without filters"""
        mock_model_objects.__iter__ = MagicMock(return_value=iter([self.sample_model, self.disabled_model]))
        mock_model_objects.__len__ = MagicMock(return_value=2)

        result = models.get_model()

        assert result == [self.sample_model, self.disabled_model]

    @patch("server.api.core.models.bootstrap.MODEL_OBJECTS")
    def test_get_model_by_id_found(self, mock_model_objects):
        """Test getting model by ID when it exists"""
        mock_model_objects.__iter__ = MagicMock(return_value=iter([self.sample_model]))
        mock_model_objects.__len__ = MagicMock(return_value=1)

        result = models.get_model(model_id="test-model")

        assert result == self.sample_model

    @patch("server.api.core.models.bootstrap.MODEL_OBJECTS")
    def test_get_model_by_id_not_found(self, mock_model_objects):
        """Test getting model by ID when it doesn't exist"""
        mock_model_objects.__iter__ = MagicMock(return_value=iter([self.sample_model]))
        mock_model_objects.__len__ = MagicMock(return_value=1)

        with pytest.raises(UnknownModelError, match="nonexistent not found"):
            models.get_model(model_id="nonexistent")

    @patch("server.api.core.models.bootstrap.MODEL_OBJECTS")
    def test_get_model_by_provider(self, mock_model_objects):
        """Test filtering models by provider"""
        all_models = [self.sample_model, self.disabled_model]
        mock_model_objects.__iter__ = MagicMock(return_value=iter(all_models))
        mock_model_objects.__len__ = MagicMock(return_value=len(all_models))

        result = models.get_model(model_provider="openai")

        # Since only one model matches provider="openai", it should return the single object
        assert result == self.sample_model

    @patch("server.api.core.models.bootstrap.MODEL_OBJECTS")
    def test_get_model_by_type(self, mock_model_objects):
        """Test filtering models by type"""
        all_models = [self.sample_model, self.disabled_model]
        mock_model_objects.__iter__ = MagicMock(return_value=iter(all_models))
        mock_model_objects.__len__ = MagicMock(return_value=len(all_models))

        result = models.get_model(model_type="ll")

        assert result == all_models

    @patch("server.api.core.models.bootstrap.MODEL_OBJECTS")
    def test_get_model_exclude_disabled(self, mock_model_objects):
        """Test excluding disabled models"""
        all_models = [self.sample_model, self.disabled_model]
        mock_model_objects.__iter__ = MagicMock(return_value=iter(all_models))
        mock_model_objects.__len__ = MagicMock(return_value=len(all_models))

        result = models.get_model(include_disabled=False)

        # Since only one model is enabled, it should return the single object
        assert result == self.sample_model

    @patch("server.api.core.models.bootstrap.MODEL_OBJECTS")
    @patch("server.api.core.models.get_model")
    @patch("common.functions.is_url_accessible")
    def test_create_model_success(self, mock_url_check, mock_get_model, mock_model_objects):
        """Test successful model creation"""
        mock_model_objects.append = MagicMock()
        mock_get_model.side_effect = [
            UnknownModelError("test-model not found"),  # First call should fail (model doesn't exist)
            self.sample_model,  # Second call returns the created model
        ]
        mock_url_check.return_value = (True, None)

        result = models.create_model(self.sample_model)

        mock_model_objects.append.assert_called_once_with(self.sample_model)
        assert result == self.sample_model

    @patch("server.api.core.models.bootstrap.MODEL_OBJECTS")
    @patch("server.api.core.models.get_model")
    def test_create_model_already_exists(self, mock_get_model, mock_model_objects):
        """Test creating model that already exists"""
        mock_get_model.return_value = self.sample_model  # Model already exists

        with pytest.raises(ExistsModelError, match="Model: openai/test-model already exists"):
            models.create_model(self.sample_model)

    @patch("server.api.core.models.bootstrap.MODEL_OBJECTS")
    @patch("server.api.core.models.get_model")
    @patch("common.functions.is_url_accessible")
    def test_create_model_unreachable_url(self, mock_url_check, mock_get_model, mock_model_objects):
        """Test creating model with unreachable URL"""
        mock_model_objects.append = MagicMock()

        # Create a copy of the model that will be modified
        test_model = Model(
            id="test-model",
            provider="openai",
            type="ll",
            enabled=True,  # Start as enabled
            api_base="https://api.openai.com",
        )

        modified_model = Model(
            id="test-model",
            provider="openai",
            type="ll",
            enabled=False,  # Will be disabled due to URL check
            api_base="https://api.openai.com",
        )

        mock_get_model.side_effect = [UnknownModelError("test-model not found"), modified_model]
        mock_url_check.return_value = (False, "Connection failed")

        result = models.create_model(test_model)

        assert result.enabled is False

    @patch("server.api.core.models.bootstrap.MODEL_OBJECTS")
    @patch("server.api.core.models.get_model")
    def test_create_model_skip_url_check(self, mock_get_model, mock_model_objects):
        """Test creating model without URL check"""
        mock_model_objects.append = MagicMock()
        mock_get_model.side_effect = [UnknownModelError("test-model not found"), self.sample_model]

        result = models.create_model(self.sample_model, check_url=False)

        assert result == self.sample_model

    @patch("server.api.core.models.bootstrap")
    def test_delete_model(self, mock_bootstrap):
        """Test model deletion"""
        mock_model_objects = [
            Model(id="test-model", provider="openai", type="ll"),
            Model(id="other-model", provider="anthropic", type="ll"),
        ]
        mock_bootstrap.MODEL_OBJECTS = mock_model_objects

        models.delete_model("openai", "test-model")

        # Verify the model was removed
        remaining_models = [m for m in mock_bootstrap.MODEL_OBJECTS if (m.id, m.provider) != ("test-model", "openai")]
        assert len(remaining_models) == 1
        assert remaining_models[0].id == "other-model"

    def test_logger_exists(self):
        """Test that logger is properly configured"""
        assert hasattr(models, "logger")
        assert models.logger.name == "api.core.models"
