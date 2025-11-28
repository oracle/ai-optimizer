"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Pytest fixtures for server/bootstrap unit tests.

Re-exports shared fixtures from test.shared_fixtures and adds unit-test specific fixtures.
"""

# pylint: disable=redefined-outer-name unused-import

from unittest.mock import MagicMock, patch

# Re-export shared fixtures for pytest discovery
from test.shared_fixtures import (
    make_database,
    make_model,
    make_oci_config,
    make_ll_settings,
    make_settings,
    make_configuration,
    temp_config_file,
    reset_config_store,
    clean_env,
)

import pytest


#################################################
# Unit Test Specific Mock Fixtures
#################################################


@pytest.fixture
def mock_oci_config_parser():
    """Mock OCI config parser for testing OCI bootstrap."""
    with patch("configparser.ConfigParser") as mock_parser:
        mock_instance = MagicMock()
        mock_instance.sections.return_value = []
        mock_parser.return_value = mock_instance
        yield mock_parser


@pytest.fixture
def mock_oci_config_from_file():
    """Mock oci.config.from_file for testing OCI bootstrap."""
    with patch("oci.config.from_file") as mock_from_file:
        yield mock_from_file


@pytest.fixture
def mock_is_url_accessible():
    """Mock is_url_accessible for testing model bootstrap."""
    with patch("server.bootstrap.models.is_url_accessible") as mock_accessible:
        mock_accessible.return_value = (True, "OK")
        yield mock_accessible
