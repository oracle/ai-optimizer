"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Consolidated tests for API v1 module configuration (routers and loggers).
These parameterized tests replace individual boilerplate tests in each module file.
"""

import pytest

from server.api.v1 import chat
from server.api.v1 import databases
from server.api.v1 import embed
from server.api.v1 import mcp
from server.api.v1 import mcp_prompts
from server.api.v1 import models
from server.api.v1 import oci
from server.api.v1 import settings
from server.api.v1 import testbed


# Module configurations for parameterized tests
API_V1_MODULES = [
    pytest.param(chat, "endpoints.v1.chat", id="chat"),
    pytest.param(databases, "endpoints.v1.databases", id="databases"),
    pytest.param(embed, "api.v1.embed", id="embed"),
    pytest.param(mcp, "api.v1.mcp", id="mcp"),
    pytest.param(mcp_prompts, "api.v1.mcp_prompts", id="mcp_prompts"),
    pytest.param(models, "endpoints.v1.models", id="models"),
    pytest.param(oci, "endpoints.v1.oci", id="oci"),
    pytest.param(settings, "endpoints.v1.settings", id="settings"),
    pytest.param(testbed, "endpoints.v1.testbed", id="testbed"),
]

# Expected routes for each module
MODULE_ROUTES = {
    "chat": ["/completions", "/streams", "/history"],
    "databases": ["", "/{name}"],
    "embed": ["/{vs}", "/{vs}/files", "/comment", "/sql/store", "/web/store", "/local/store", "/", "/refresh"],
    "mcp": ["/client", "/tools", "/resources"],
    "mcp_prompts": ["/prompts", "/prompts/{name}"],
    "models": ["", "/supported", "/{model_provider}/{model_id:path}"],
    "oci": ["", "/{auth_profile}", "/regions/{auth_profile}", "/genai/{auth_profile}", "/compartments/{auth_profile}"],
    "settings": ["", "/load/file", "/load/json"],
    "testbed": [
        "/testsets",
        "/evaluations",
        "/evaluation",
        "/testset_qa",
        "/testset_delete/{tid}",
        "/testset_load",
        "/testset_generate",
        "/evaluate",
    ],
}


class TestRouterConfiguration:
    """Parameterized tests for router configuration across all API v1 modules."""

    @pytest.mark.parametrize("module,_logger_name", API_V1_MODULES)
    def test_auth_router_exists(self, module, _logger_name):
        """Each API v1 module should have an auth router defined."""
        assert hasattr(module, "auth"), f"{module.__name__} should have 'auth' router"

    @pytest.mark.parametrize(
        "module,expected_routes",
        [
            pytest.param(chat, MODULE_ROUTES["chat"], id="chat"),
            pytest.param(databases, MODULE_ROUTES["databases"], id="databases"),
            pytest.param(embed, MODULE_ROUTES["embed"], id="embed"),
            pytest.param(mcp, MODULE_ROUTES["mcp"], id="mcp"),
            pytest.param(mcp_prompts, MODULE_ROUTES["mcp_prompts"], id="mcp_prompts"),
            pytest.param(models, MODULE_ROUTES["models"], id="models"),
            pytest.param(oci, MODULE_ROUTES["oci"], id="oci"),
            pytest.param(settings, MODULE_ROUTES["settings"], id="settings"),
            pytest.param(testbed, MODULE_ROUTES["testbed"], id="testbed"),
        ],
    )
    def test_auth_router_has_routes(self, module, expected_routes):
        """Each API v1 module should have the expected routes registered."""
        routes = [route.path for route in module.auth.routes]
        for expected_route in expected_routes:
            assert expected_route in routes, f"{module.__name__} missing route: {expected_route}"


class TestLoggerConfiguration:
    """Parameterized tests for LOGGER configuration across all API v1 modules."""

    @pytest.mark.parametrize("module,_logger_name", API_V1_MODULES)
    def test_logger_exists(self, module, _logger_name):
        """Each API v1 module should have a LOGGER configured."""
        assert hasattr(module, "LOGGER"), f"{module.__name__} should have 'LOGGER'"

    @pytest.mark.parametrize("module,expected_name", API_V1_MODULES)
    def test_logger_name(self, module, expected_name):
        """Each API v1 module LOGGER should have the correct name."""
        assert module.LOGGER.name == expected_name, (
            f"{module.__name__} LOGGER name should be '{expected_name}', got '{module.LOGGER.name}'"
        )
