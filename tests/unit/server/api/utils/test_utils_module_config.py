"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Consolidated tests for API utils module configuration (loggers).
These parameterized tests replace individual boilerplate tests in each module file.
"""

import pytest

from server.api.utils import chat as utils_chat
from server.api.utils import databases as utils_databases
from server.api.utils import embed as utils_embed
from server.api.utils import mcp
from server.api.utils import models as utils_models
from server.api.utils import oci as utils_oci
from server.api.utils import settings as utils_settings
from server.api.utils import testbed as utils_testbed


# Module configurations for parameterized tests
API_UTILS_MODULES = [
    pytest.param(utils_chat, "api.utils.chat", id="chat"),
    pytest.param(utils_databases, "api.utils.database", id="databases"),
    pytest.param(utils_embed, "api.utils.embed", id="embed"),
    pytest.param(mcp, "api.utils.mcp", id="mcp"),
    pytest.param(utils_models, "api.utils.models", id="models"),
    pytest.param(utils_oci, "api.utils.oci", id="oci"),
    pytest.param(utils_settings, "api.core.settings", id="settings"),
    pytest.param(utils_testbed, "api.utils.testbed", id="testbed"),
]


class TestLoggerConfiguration:
    """Parameterized tests for logger configuration across all API utils modules."""

    @pytest.mark.parametrize("module,_logger_name", API_UTILS_MODULES)
    def test_logger_exists(self, module, _logger_name):
        """Each API utils module should have a logger configured."""
        assert hasattr(module, "logger"), f"{module.__name__} should have 'logger'"

    @pytest.mark.parametrize("module,expected_name", API_UTILS_MODULES)
    def test_logger_name(self, module, expected_name):
        """Each API utils module logger should have the correct name."""
        assert module.logger.name == expected_name, (
            f"{module.__name__} logger name should be '{expected_name}', got '{module.logger.name}'"
        )
