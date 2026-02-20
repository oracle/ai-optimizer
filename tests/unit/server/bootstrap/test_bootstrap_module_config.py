"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
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
        """Each bootstrap module should have a LOGGER configured."""
        assert hasattr(module, "LOGGER"), f"{module.__name__} should have 'LOGGER'"

    @pytest.mark.parametrize("module,expected_name", BOOTSTRAP_MODULES)
    def test_logger_name(self, module, expected_name):
        """Each bootstrap module LOGGER should have the correct name."""
        assert module.LOGGER.name == expected_name, (
            f"{module.__name__} LOGGER name should be '{expected_name}', got '{module.LOGGER.name}'"
        )
