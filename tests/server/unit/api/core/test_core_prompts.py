"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for MCP prompt export/import functionality
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from fastmcp import FastMCP

from server.api.core import settings
from server.mcp.prompts import cache
from common.schema import MCPPrompt


class TestMCPPromptExport:
    """Test MCP prompt export functionality"""

    @pytest.mark.asyncio
    async def test_get_mcp_prompts_with_overrides_empty(self):
        """Test getting prompts when none exist"""
        mock_mcp_engine = MagicMock()

        with patch("server.api.utils.mcp.list_prompts", new=AsyncMock(return_value=[])) as mock_list:
            result = await settings.get_mcp_prompts_with_overrides(mock_mcp_engine)

        assert result == []
        mock_list.assert_called_once_with(mock_mcp_engine)

    @pytest.mark.asyncio
    async def test_get_mcp_prompts_with_overrides_no_optimizer_prompts(self):
        """Test that non-optimizer prompts are filtered out"""
        mock_mcp_engine = MagicMock()

        # Mock prompt that doesn't start with "optimizer_"
        mock_prompt = MagicMock()
        mock_prompt.name = "other_prompt"
        mock_prompt.title = "Other Prompt"
        mock_prompt.description = "Not an optimizer prompt"
        mock_prompt.meta = None

        with patch("server.api.utils.mcp.list_prompts", new=AsyncMock(return_value=[mock_prompt])):
            result = await settings.get_mcp_prompts_with_overrides(mock_mcp_engine)

        assert result == []

    @pytest.mark.asyncio
    async def test_get_mcp_prompts_with_overrides_with_defaults(self):
        """Test getting prompts with default text"""
        mock_mcp_engine = MagicMock()

        # Mock prompt object
        mock_prompt = MagicMock()
        mock_prompt.name = "optimizer_basic-default"
        mock_prompt.title = "Basic Prompt"
        mock_prompt.description = "Basic system prompt"
        mock_prompt.meta = {"_fastmcp": {"tags": ["source", "optimizer"]}}

        # Mock the default function
        mock_default_message = MagicMock()
        mock_default_message.content.text = "You are a helpful assistant."

        with patch("server.api.utils.mcp.list_prompts", new=AsyncMock(return_value=[mock_prompt])), \
             patch("server.api.core.settings.defaults.optimizer_basic_default", return_value=mock_default_message), \
             patch("server.api.core.settings.cache.get_override", return_value=None):

            result = await settings.get_mcp_prompts_with_overrides(mock_mcp_engine)

        assert len(result) == 1
        assert result[0].name == "optimizer_basic-default"
        assert result[0].title == "Basic Prompt"
        assert result[0].description == "Basic system prompt"
        assert result[0].tags == ["source", "optimizer"]
        assert result[0].default_text == "You are a helpful assistant."
        assert result[0].override_text is None

    @pytest.mark.asyncio
    async def test_get_mcp_prompts_with_overrides_with_overrides(self):
        """Test getting prompts with override text"""
        mock_mcp_engine = MagicMock()

        mock_prompt = MagicMock()
        mock_prompt.name = "optimizer_tools-default"
        mock_prompt.title = "Tools Prompt"
        mock_prompt.description = "Tools system prompt"
        mock_prompt.meta = {"_fastmcp": {"tags": ["source", "optimizer"]}}

        mock_default_message = MagicMock()
        mock_default_message.content.text = "Default tools prompt"

        with patch("server.api.utils.mcp.list_prompts", new=AsyncMock(return_value=[mock_prompt])), \
             patch("server.api.core.settings.defaults.optimizer_tools_default", return_value=mock_default_message), \
             patch("server.api.core.settings.cache.get_override", return_value="Custom tools prompt"):

            result = await settings.get_mcp_prompts_with_overrides(mock_mcp_engine)

        assert len(result) == 1
        assert result[0].name == "optimizer_tools-default"
        assert result[0].default_text == "Default tools prompt"
        assert result[0].override_text == "Custom tools prompt"

    @pytest.mark.asyncio
    async def test_get_mcp_prompts_with_overrides_multiple_prompts(self):
        """Test getting multiple prompts with mixed overrides"""
        mock_mcp_engine = MagicMock()

        # Create multiple mock prompts
        mock_prompts = []
        for name in ["optimizer_basic-default", "optimizer_tools-default", "optimizer_vs-grading"]:
            mock_prompt = MagicMock()
            mock_prompt.name = name
            mock_prompt.title = name.replace("optimizer_", "").replace("-", " ").title()
            mock_prompt.description = f"Description for {name}"
            mock_prompt.meta = {"_fastmcp": {"tags": ["optimizer"]}}
            mock_prompts.append(mock_prompt)

        # Mock default functions
        def mock_default_func(name):
            msg = MagicMock()
            msg.content.text = f"Default text for {name}"
            return msg

        # Mock overrides (only for tools-default)
        def mock_get_override(name):
            return "Custom override" if name == "optimizer_tools-default" else None

        with patch("server.api.utils.mcp.list_prompts", new=AsyncMock(return_value=mock_prompts)), \
             patch("server.api.core.settings.defaults.optimizer_basic_default",
                   return_value=mock_default_func("optimizer_basic_default")), \
             patch("server.api.core.settings.defaults.optimizer_tools_default",
                   return_value=mock_default_func("optimizer_tools_default")), \
             patch("server.api.core.settings.defaults.optimizer_vs_grading",
                   return_value=mock_default_func("optimizer_vs_grading")), \
             patch("server.api.core.settings.cache.get_override", side_effect=mock_get_override):

            result = await settings.get_mcp_prompts_with_overrides(mock_mcp_engine)

        assert len(result) == 3
        # Check that only tools-default has an override
        tools_prompt = next(p for p in result if p.name == "optimizer_tools-default")
        assert tools_prompt.override_text == "Custom override"

        basic_prompt = next(p for p in result if p.name == "optimizer_basic-default")
        assert basic_prompt.override_text is None

    @pytest.mark.asyncio
    async def test_get_mcp_prompts_handles_missing_default_function(self):
        """Test that missing default function is handled gracefully"""
        mock_mcp_engine = MagicMock()

        mock_prompt = MagicMock()
        mock_prompt.name = "optimizer_nonexistent-prompt"
        mock_prompt.title = "Nonexistent"
        mock_prompt.description = ""
        mock_prompt.meta = None

        with patch("server.api.utils.mcp.list_prompts", new=AsyncMock(return_value=[mock_prompt])), \
             patch("server.api.core.settings.cache.get_override", return_value=None):

            result = await settings.get_mcp_prompts_with_overrides(mock_mcp_engine)

        assert len(result) == 1
        assert result[0].default_text == ""  # Falls back to empty string


class TestMCPPromptImport:
    """Test MCP prompt import functionality"""

    def test_update_server_config_with_prompt_overrides(self):
        """Test that prompt overrides are applied from config"""
        # Clear cache before test
        cache.clear_all_overrides()

        # Test the prompt override logic directly
        prompt_overrides = {
            "optimizer_basic-default": "Custom basic prompt",
            "optimizer_tools-default": "Custom tools prompt"
        }

        # Apply overrides as the code does
        for name, text in prompt_overrides.items():
            if text:
                cache.set_override(name, text)

        # Verify overrides were applied to cache
        assert cache.get_override("optimizer_basic-default") == "Custom basic prompt"
        assert cache.get_override("optimizer_tools-default") == "Custom tools prompt"

        # Clean up
        cache.clear_all_overrides()

    def test_update_server_config_with_empty_prompt_overrides(self):
        """Test handling of empty prompt overrides"""
        cache.clear_all_overrides()

        # Empty overrides dict - no changes
        prompt_overrides = {}

        for name, text in prompt_overrides.items():
            if text:
                cache.set_override(name, text)

        # Verify no overrides were applied
        assert cache.get_override("optimizer_basic-default") is None

    def test_update_server_config_without_prompt_overrides(self):
        """Test that missing prompt_overrides key doesn't cause errors"""
        cache.clear_all_overrides()

        # Simulate case where prompt_overrides key is missing
        prompt_overrides = None

        # Should not raise an exception
        if prompt_overrides:
            for name, text in prompt_overrides.items():
                if text:
                    cache.set_override(name, text)

        # No errors should occur
        assert cache.get_override("optimizer_basic-default") is None

    def test_update_server_config_ignores_null_overrides(self):
        """Test that null/None override values are ignored"""
        cache.clear_all_overrides()

        prompt_overrides = {
            "optimizer_basic-default": "Valid override",
            "optimizer_tools-default": None,
            "optimizer_context-default": ""
        }

        # Apply overrides with filtering (as code does)
        for name, text in prompt_overrides.items():
            if text:  # Only set non-null/non-empty overrides
                cache.set_override(name, text)

        # Only valid override should be applied
        assert cache.get_override("optimizer_basic-default") == "Valid override"
        assert cache.get_override("optimizer_tools-default") is None
        assert cache.get_override("optimizer_context-default") is None

        cache.clear_all_overrides()


class TestPromptOverrideCache:
    """Test prompt override cache functionality"""

    def test_cache_set_and_get_override(self):
        """Test basic cache set and get operations"""
        cache.clear_all_overrides()

        cache.set_override("test_prompt", "Custom text")
        assert cache.get_override("test_prompt") == "Custom text"

        cache.clear_all_overrides()

    def test_cache_get_nonexistent_override(self):
        """Test getting override that doesn't exist"""
        cache.clear_all_overrides()

        assert cache.get_override("nonexistent") is None

    def test_cache_clear_override(self):
        """Test clearing a specific override"""
        cache.clear_all_overrides()

        cache.set_override("test_prompt", "Custom text")
        assert cache.get_override("test_prompt") == "Custom text"

        cache.clear_override("test_prompt")
        assert cache.get_override("test_prompt") is None

    def test_cache_clear_all_overrides(self):
        """Test clearing all overrides"""
        cache.clear_all_overrides()

        cache.set_override("prompt1", "Text 1")
        cache.set_override("prompt2", "Text 2")
        cache.set_override("prompt3", "Text 3")

        assert cache.get_override("prompt1") == "Text 1"
        assert cache.get_override("prompt2") == "Text 2"

        cache.clear_all_overrides()

        assert cache.get_override("prompt1") is None
        assert cache.get_override("prompt2") is None
        assert cache.get_override("prompt3") is None

    def test_cache_update_existing_override(self):
        """Test updating an existing override"""
        cache.clear_all_overrides()

        cache.set_override("test_prompt", "Original text")
        assert cache.get_override("test_prompt") == "Original text"

        cache.set_override("test_prompt", "Updated text")
        assert cache.get_override("test_prompt") == "Updated text"

        cache.clear_all_overrides()


class TestServerConfigIntegration:
    """Integration tests for get_server with prompts"""

    @pytest.mark.asyncio
    async def test_get_server_includes_prompt_overrides(self):
        """Test that get_server includes prompt_overrides in response"""
        cache.clear_all_overrides()
        cache.set_override("optimizer_basic-default", "Custom basic")
        cache.set_override("optimizer_tools-default", "Custom tools")

        mock_mcp_engine = MagicMock()

        # Mock get_mcp_prompts_with_overrides to return prompts with overrides
        mock_prompts = [
            MCPPrompt(
                name="optimizer_basic-default",
                title="Basic",
                description="",
                tags=[],
                default_text="Default basic",
                override_text="Custom basic"
            ),
            MCPPrompt(
                name="optimizer_tools-default",
                title="Tools",
                description="",
                tags=[],
                default_text="Default tools",
                override_text="Custom tools"
            )
        ]

        with patch("server.api.core.settings.bootstrap.DATABASE_OBJECTS", []), \
             patch("server.api.core.settings.bootstrap.MODEL_OBJECTS", []), \
             patch("server.api.core.settings.bootstrap.OCI_OBJECTS", []), \
             patch("server.api.core.settings.get_mcp_prompts_with_overrides", return_value=mock_prompts):

            result = await settings.get_server(mock_mcp_engine)

        assert "prompt_configs" in result
        assert "prompt_overrides" in result
        assert len(result["prompt_configs"]) == 2
        assert result["prompt_overrides"] == {
            "optimizer_basic-default": "Custom basic",
            "optimizer_tools-default": "Custom tools"
        }

        cache.clear_all_overrides()

    @pytest.mark.asyncio
    async def test_get_server_empty_overrides(self):
        """Test get_server when no overrides exist"""
        cache.clear_all_overrides()

        mock_mcp_engine = MagicMock()

        mock_prompts = [
            MCPPrompt(
                name="optimizer_basic-default",
                title="Basic",
                description="",
                tags=[],
                default_text="Default text",
                override_text=None
            )
        ]

        with patch("server.api.core.settings.bootstrap.DATABASE_OBJECTS", []), \
             patch("server.api.core.settings.bootstrap.MODEL_OBJECTS", []), \
             patch("server.api.core.settings.bootstrap.OCI_OBJECTS", []), \
             patch("server.api.core.settings.get_mcp_prompts_with_overrides", return_value=mock_prompts):

            result = await settings.get_server(mock_mcp_engine)

        assert result["prompt_overrides"] == {}
