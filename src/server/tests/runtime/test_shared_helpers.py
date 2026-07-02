"""Tests for shared runtime test helpers."""

import io
import json
from unittest.mock import patch

import pytest

from server.tests.constants import TEST_OLLAMA_MODEL_ID
from server.tests.runtime.shared_helpers import ollama_available


@pytest.mark.unit
@pytest.mark.parametrize(
    ("models", "expected"),
    [
        ([{"name": TEST_OLLAMA_MODEL_ID}], True),
        ([{"name": "another-model:latest"}], False),
    ],
)
def test_ollama_available_checks_required_model(models, expected):
    """A reachable server is unavailable when the required model is absent."""
    response = io.BytesIO(json.dumps({"models": models}).encode())

    with patch("urllib.request.urlopen", return_value=response):
        assert ollama_available(TEST_OLLAMA_MODEL_ID) is expected
