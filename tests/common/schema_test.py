"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

from common.schema import Settings, LanguageModelParameters
import pytest
import unittest.mock as mock

def test_create_settings_from_json_returns_right_settings():
    json = """
    { "client": "default",
      "ll_model": { "context_length": null,
                    "frequency_penalty": 0.0,
                    "max_completion_tokens": 256,
                    "presence_penalty": 0.0,
                    "temperature": 1.2,
                    "top_p": 1.0,
                    "streaming": false,
                    "model": null,
                    "chat_history": true },
      "prompts": { "ctx": "Basic Example",
                   "sys": "Basic Example" },
      "rag": { "database": "DEFAULT",
               "vector_store": null,
               "alias": null,
               "model": null,
               "chunk_size": null,
               "chunk_overlap": null,
               "distance_metric": null,
               "index_type": null,
               "rag_enabled": false,
               "grading": true,
               "search_type": "Similarity",
               "top_k": 4,
               "score_threshold": 0.0,
               "fetch_k": 20,
               "lambda_mult": 0.5 },
      "oci": { "auth_profile" :"DEFAULT" }
    }
    """
    client = "default"
    settings_from_json = Settings.from_json(client, json)
    some_settings = Settings(client=client)
    some_settings.ll_model.temperature = 1.2
    print(f"LEFT:  {settings_from_json}")
    print(f"RIGHT: {some_settings}")
    assert settings_from_json == some_settings


def test_json_to_file_writes_settings_json():
    client = "default"
    path = 'some_path/some_file.json'
    default_settings = Settings(client=client)
    default_settings.ll_model.top_p = 0.5

    mocked_open = mock.mock_open()
    with mock.patch('builtins.open', mocked_open) as mock_open:
        default_settings.json_to_file(path)
        mock_open.assert_called_with(path, 'w')
        mock_open().write.assert_called_once_with(default_settings.model_dump_json())

