"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/api/v1/mcp_prompts.py
Tests for MCP prompt management endpoints.
"""

from unittest.mock import patch, MagicMock, AsyncMock
import pytest
from fastapi import HTTPException

from server.api.v1 import mcp_prompts


class TestMcpListPrompts:
    """Tests for the mcp_list_prompts endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.mcp_prompts.utils_mcp.list_prompts")
    async def test_mcp_list_prompts_metadata_only(self, mock_list_prompts, mock_fastmcp):
        """mcp_list_prompts should return metadata only when full=False."""
        mock_prompt = MagicMock()
        mock_prompt.name = "optimizer_test-prompt"
        mock_prompt.model_dump.return_value = {"name": "optimizer_test-prompt", "description": "Test"}
        mock_list_prompts.return_value = [mock_prompt]

        result = await mcp_prompts.mcp_list_prompts(mcp_engine=mock_fastmcp, full=False)

        assert len(result) == 1
        assert result[0]["name"] == "optimizer_test-prompt"
        mock_list_prompts.assert_called_once_with(mock_fastmcp)

    @pytest.mark.asyncio
    @patch("server.api.v1.mcp_prompts.utils_settings.get_mcp_prompts_with_overrides")
    async def test_mcp_list_prompts_full(self, mock_get_prompts, mock_fastmcp, make_mcp_prompt):
        """mcp_list_prompts should return full prompts with text when full=True."""
        mock_prompt = make_mcp_prompt(name="optimizer_test-prompt")
        mock_get_prompts.return_value = [mock_prompt]

        result = await mcp_prompts.mcp_list_prompts(mcp_engine=mock_fastmcp, full=True)

        assert len(result) == 1
        assert "text" in result[0]
        mock_get_prompts.assert_called_once_with(mock_fastmcp)

    @pytest.mark.asyncio
    @patch("server.api.v1.mcp_prompts.utils_mcp.list_prompts")
    async def test_mcp_list_prompts_filters_non_optimizer_prompts(self, mock_list_prompts, mock_fastmcp):
        """mcp_list_prompts should filter out non-optimizer prompts."""
        optimizer_prompt = MagicMock()
        optimizer_prompt.name = "optimizer_test-prompt"
        optimizer_prompt.model_dump.return_value = {"name": "optimizer_test-prompt"}

        other_prompt = MagicMock()
        other_prompt.name = "other-prompt"
        other_prompt.model_dump.return_value = {"name": "other-prompt"}

        mock_list_prompts.return_value = [optimizer_prompt, other_prompt]

        result = await mcp_prompts.mcp_list_prompts(mcp_engine=mock_fastmcp, full=False)

        assert len(result) == 1
        assert result[0]["name"] == "optimizer_test-prompt"

    @pytest.mark.asyncio
    @patch("server.api.v1.mcp_prompts.utils_mcp.list_prompts")
    async def test_mcp_list_prompts_empty_list(self, mock_list_prompts, mock_fastmcp):
        """mcp_list_prompts should return empty list when no prompts."""
        mock_list_prompts.return_value = []

        result = await mcp_prompts.mcp_list_prompts(mcp_engine=mock_fastmcp, full=False)

        assert result == []


class TestMcpGetPrompt:
    """Tests for the mcp_get_prompt endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.mcp_prompts.Client")
    async def test_mcp_get_prompt_success(self, mock_client_class, mock_fastmcp):
        """mcp_get_prompt should return prompt content."""
        mock_prompt_result = MagicMock()
        mock_prompt_result.messages = [{"role": "user", "content": "Test content"}]

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get_prompt = AsyncMock(return_value=mock_prompt_result)
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        result = await mcp_prompts.mcp_get_prompt(name="optimizer_test-prompt", mcp_engine=mock_fastmcp)

        assert result == mock_prompt_result
        mock_client.get_prompt.assert_called_once_with(name="optimizer_test-prompt")

    @pytest.mark.asyncio
    @patch("server.api.v1.mcp_prompts.Client")
    async def test_mcp_get_prompt_closes_client(self, mock_client_class, mock_fastmcp):
        """mcp_get_prompt should close client after use."""
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get_prompt = AsyncMock(return_value=MagicMock())
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        await mcp_prompts.mcp_get_prompt(name="test-prompt", mcp_engine=mock_fastmcp)

        mock_client.close.assert_called_once()


class TestMcpUpdatePrompt:
    """Tests for the mcp_update_prompt endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.mcp_prompts.Client")
    @patch("server.api.v1.mcp_prompts.cache")
    async def test_mcp_update_prompt_success(self, mock_cache, mock_client_class, mock_fastmcp):
        """mcp_update_prompt should update prompt and return success."""
        mock_prompt = MagicMock()
        mock_prompt.name = "optimizer_test-prompt"

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.list_prompts = AsyncMock(return_value=[mock_prompt])
        mock_client_class.return_value = mock_client

        payload = {"instructions": "You are a helpful assistant."}

        result = await mcp_prompts.mcp_update_prompt(
            name="optimizer_test-prompt", payload=payload, mcp_engine=mock_fastmcp
        )

        assert result["name"] == "optimizer_test-prompt"
        assert "updated successfully" in result["message"]
        mock_cache.set_override.assert_called_once_with("optimizer_test-prompt", "You are a helpful assistant.")

    @pytest.mark.asyncio
    @patch("server.api.v1.mcp_prompts.Client")
    async def test_mcp_update_prompt_missing_instructions(self, _mock_client_class, mock_fastmcp):
        """mcp_update_prompt should raise 400 when instructions missing."""
        payload = {"other_field": "value"}

        with pytest.raises(HTTPException) as exc_info:
            await mcp_prompts.mcp_update_prompt(name="test-prompt", payload=payload, mcp_engine=mock_fastmcp)

        assert exc_info.value.status_code == 400
        assert "instructions" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    @patch("server.api.v1.mcp_prompts.Client")
    async def test_mcp_update_prompt_not_found(self, mock_client_class, mock_fastmcp):
        """mcp_update_prompt should raise 404 when prompt not found."""
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.list_prompts = AsyncMock(return_value=[])
        mock_client_class.return_value = mock_client

        payload = {"instructions": "New instructions"}

        with pytest.raises(HTTPException) as exc_info:
            await mcp_prompts.mcp_update_prompt(name="nonexistent-prompt", payload=payload, mcp_engine=mock_fastmcp)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    @patch("server.api.v1.mcp_prompts.Client")
    @patch("server.api.v1.mcp_prompts.cache")
    async def test_mcp_update_prompt_handles_exception(self, mock_cache, mock_client_class, mock_fastmcp):
        """mcp_update_prompt should raise 500 on unexpected exception."""
        mock_prompt = MagicMock()
        mock_prompt.name = "optimizer_test-prompt"

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.list_prompts = AsyncMock(return_value=[mock_prompt])
        mock_client_class.return_value = mock_client

        mock_cache.set_override.side_effect = RuntimeError("Cache error")

        payload = {"instructions": "New instructions"}

        with pytest.raises(HTTPException) as exc_info:
            await mcp_prompts.mcp_update_prompt(name="optimizer_test-prompt", payload=payload, mcp_engine=mock_fastmcp)

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_mcp_update_prompt_none_instructions(self, mock_fastmcp):
        """mcp_update_prompt should raise 400 when instructions is None."""
        payload = {"instructions": None}

        with pytest.raises(HTTPException) as exc_info:
            await mcp_prompts.mcp_update_prompt(name="test-prompt", payload=payload, mcp_engine=mock_fastmcp)

        assert exc_info.value.status_code == 400


class TestMcpResetPrompts:
    """Tests for the mcp_reset_prompts endpoint."""

    @pytest.mark.asyncio
    @patch("server.api.v1.mcp_prompts.cache")
    async def test_mcp_reset_prompts_success(self, mock_cache):
        """mcp_reset_prompts should clear all overrides and return success."""
        mock_cache.clear_all_overrides.return_value = None

        result = await mcp_prompts.mcp_reset_prompts()

        assert "message" in result
        assert "reset to default values" in result["message"]
        mock_cache.clear_all_overrides.assert_called_once()

    @pytest.mark.asyncio
    @patch("server.api.v1.mcp_prompts.cache")
    async def test_mcp_reset_prompts_handles_exception(self, mock_cache):
        """mcp_reset_prompts should raise 500 on exception."""
        mock_cache.clear_all_overrides.side_effect = RuntimeError("Cache clear error")

        with pytest.raises(HTTPException) as exc_info:
            await mcp_prompts.mcp_reset_prompts()

        assert exc_info.value.status_code == 500
        assert "Failed to reset prompts" in str(exc_info.value.detail)
