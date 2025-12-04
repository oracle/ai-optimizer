"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Consolidated tests for bootstrap module configuration (loggers).
These parameterized tests replace individual boilerplate tests in each module file.
"""

import pytest

from server.bootstrap import bootstrap
from server.bootstrap import configfile
from server.bootstrap import databases as databases_module
from server.bootstrap import models as models_module
from server.bootstrap import oci as oci_module
from server.bootstrap import settings as settings_module


# Module configurations for parameterized tests
BOOTSTRAP_MODULES = [
    pytest.param(bootstrap, "bootstrap", id="bootstrap"),
    pytest.param(configfile, "bootstrap.configfile", id="configfile"),
    pytest.param(databases_module, "bootstrap.databases", id="databases"),
    pytest.param(models_module, "bootstrap.models", id="models"),
    pytest.param(oci_module, "bootstrap.oci", id="oci"),
    pytest.param(settings_module, "bootstrap.settings", id="settings"),
]


class TestLoggerConfiguration:
    """Parameterized tests for logger configuration across all bootstrap modules."""

    @pytest.mark.parametrize("module,_logger_name", BOOTSTRAP_MODULES)
    def test_logger_exists(self, module, _logger_name):
        """Each bootstrap module should have a logger configured."""
        assert hasattr(module, "logger"), f"{module.__name__} should have 'logger'"

    @pytest.mark.parametrize("module,expected_name", BOOTSTRAP_MODULES)
    def test_logger_name(self, module, expected_name):
        """Each bootstrap module logger should have the correct name."""
        assert module.logger.name == expected_name, (
            f"{module.__name__} logger name should be '{expected_name}', got '{module.logger.name}'"
        )
