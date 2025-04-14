"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
"""

from server.bootstrap.settings_def import restore_or_default_settings
from common.schema import Settings, LanguageModelParameters
import pytest
import os
import unittest.mock as mock


def test_restore_returns_default_settings_on_invalid_settings_file():
    client = "default"
    settings_from_json = restore_or_default_settings(client, "invalid_file.json")
    default_settings = Settings(client=client)
    assert settings_from_json == default_settings


@pytest.mark.parametrize(('is_file', 'has_access', 'file_read'),
    [
        (True, True, True),
        (False, True, False),
        (True, False, False),
        (False, False, False),
     ])
@mock.patch('os.access')
@mock.patch('os.path.isfile')
def test_restore_reads_file_if_isfile_and_has_access(mock_isfile, mock_access, is_file, has_access, file_read):
    client = "default"
    path = 'some_path/some_file.json'
    mock_isfile.return_value = is_file
    mock_access.return_value = has_access
    mocked_open = mock.mock_open(read_data="")
    with mock.patch('builtins.open', mocked_open) as mock_open:
        settings_from_file = restore_or_default_settings(client, path)
        if file_read:
            mock_open.assert_called_with(path, 'r')

    mock_isfile.assert_called_with(path)
    if is_file:
        mock_access.assert_called_with(path, os.R_OK)


@mock.patch('os.access')
@mock.patch('os.path.isfile')
def test_restore_returns_default_settings_from_bad_json(mock_isfile, mock_access):
    client = "default"
    path = 'some_path/some_file.json'
    json = """
    { "client": "default",
      "prompts": { "ctx": "Another Example",
                   "sys": "Yet another Example" },
      "nothing_else_here" }
    """
    mock_isfile.return_value = True
    mock_access.return_value = True
    mocked_open = mock.mock_open(read_data=json)
    with mock.patch('builtins.open', mocked_open) as mock_open:
        settings_from_file = restore_or_default_settings(client, path)
        mock_open.assert_called_with(path, 'r')

    default_settings = Settings(client=client)

    mock_isfile.assert_called_once_with(path)
    mock_access.assert_called_once_with(path, os.R_OK)
    assert settings_from_file == default_settings


@mock.patch('os.access')
@mock.patch('os.path.isfile')
def test_restore_returns_settings_from_json(mock_isfile, mock_access):
    client = "default"
    path = 'some_path/some_file.json'
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
    mock_isfile.return_value = True
    mock_access.return_value = True
    mocked_open = mock.mock_open(read_data=json)
    with mock.patch('builtins.open', mocked_open) as mock_open:
        settings_from_file = restore_or_default_settings(client, path)
        mock_open.assert_called_with(path, 'r')

    default_settings = Settings(client=client)
    default_settings.ll_model.temperature = 1.2

    mock_isfile.assert_called_once_with(path)
    mock_access.assert_called_once_with(path, os.R_OK)
    assert settings_from_file == default_settings

