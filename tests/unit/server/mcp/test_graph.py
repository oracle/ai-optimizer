"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for server/mcp/graph.py

Tests completion kwargs building logic.
"""

from server.mcp.graph import _build_completion_kwargs


class TestCompletionKwargs:
    """Tests for _build_completion_kwargs function."""

    def test_no_tool_choice_without_forcing(self):
        """Test that tool_choice is NOT set when not explicitly forced."""
        messages = [{"role": "user", "content": "test"}]
        ll_raw = {"model": "gpt-4o-mini", "temperature": 0.0}
        tools = [
            {"type": "function", "function": {"name": "optimizer_vs-retriever", "description": "Retrieve docs"}},
            {"type": "function", "function": {"name": "optimizer_vs-storage", "description": "List stores"}},
        ]

        kwargs = _build_completion_kwargs(messages, ll_raw, tools)

        assert "tool_choice" not in kwargs
        assert kwargs["tools"] == tools

    def test_tool_choice_applied_when_forced(self):
        """Test that tool_choice is applied when explicitly passed (single-tool mode)."""
        messages = [{"role": "user", "content": "test"}]
        ll_raw = {"model": "gpt-4o-mini", "temperature": 0.0}
        tools = [
            {"type": "function", "function": {"name": "optimizer_vs-retriever", "description": "Retrieve docs"}},
        ]
        tool_choice = {"type": "function", "function": {"name": "optimizer_vs-retriever"}}

        kwargs = _build_completion_kwargs(messages, ll_raw, tools, tool_choice)

        assert "tool_choice" in kwargs
        assert kwargs["tool_choice"] == tool_choice
        assert kwargs["tools"] == tools

    def test_no_tool_choice_with_mixed_tools(self):
        """Test that tool_choice is NOT set when VS and SQL tools are both present."""
        messages = [{"role": "user", "content": "test"}]
        ll_raw = {"model": "gpt-4o-mini", "temperature": 0.0}
        tools = [
            {"type": "function", "function": {"name": "optimizer_vs-retriever", "description": "Retrieve docs"}},
            {"type": "function", "function": {"name": "sqlcl_query", "description": "Query database"}},
        ]

        kwargs = _build_completion_kwargs(messages, ll_raw, tools)

        assert "tool_choice" not in kwargs
        assert kwargs["tools"] == tools

    def test_no_tool_choice_with_sql_tools(self):
        """Test that tool_choice is NOT set when only SQL tools are present."""
        messages = [{"role": "user", "content": "test"}]
        ll_raw = {"model": "gpt-4o-mini", "temperature": 0.0}
        tools = [
            {"type": "function", "function": {"name": "sqlcl_query", "description": "Query database"}},
            {"type": "function", "function": {"name": "sqlcl_list_tables", "description": "List tables"}},
        ]

        kwargs = _build_completion_kwargs(messages, ll_raw, tools)

        assert "tool_choice" not in kwargs
        assert kwargs["tools"] == tools

    def test_no_tools_parameter_when_empty(self):
        """Test that tools parameter is not passed when empty."""
        messages = [{"role": "user", "content": "test"}]
        ll_raw = {"model": "gpt-4o-mini", "temperature": 0.0}
        tools = []

        kwargs = _build_completion_kwargs(messages, ll_raw, tools)

        assert "tools" not in kwargs
        assert "tool_choice" not in kwargs

    def test_kwargs_includes_stream_and_model(self):
        """Test that completion kwargs include required parameters."""
        messages = [{"role": "user", "content": "test"}]
        ll_raw = {"model": "gpt-4o-mini", "temperature": 0.5, "max_tokens": 1000}
        tools = []

        kwargs = _build_completion_kwargs(messages, ll_raw, tools)

        assert kwargs["stream"] is True
        assert kwargs["model"] == "gpt-4o-mini"
        assert kwargs["temperature"] == 0.5
        assert kwargs["max_tokens"] == 1000

    def test_tools_included_when_provided(self):
        """Test that tools are included in kwargs when provided."""
        messages = [{"role": "user", "content": "test"}]
        ll_raw = {"model": "gpt-4o-mini"}
        tools = [
            {"type": "function", "function": {"name": "optimizer_vs-retriever", "description": "Retrieve"}},
        ]

        kwargs = _build_completion_kwargs(messages, ll_raw, tools)

        assert "tools" in kwargs
        assert kwargs["tools"] == tools
        assert "tool_choice" not in kwargs

    def test_tool_choice_parameter_passthrough(self):
        """Test that tool_choice parameter is passed through when provided."""
        messages = [{"role": "user", "content": "test"}]
        ll_raw = {"model": "gpt-4o-mini"}
        tools = [
            {"type": "function", "function": {"name": "optimizer_vs-retriever", "description": "Retrieve"}},
        ]
        tool_choice = {"type": "function", "function": {"name": "optimizer_vs-retriever"}}

        kwargs = _build_completion_kwargs(messages, ll_raw, tools, tool_choice)

        assert "tool_choice" in kwargs
        assert kwargs["tool_choice"] == tool_choice
        assert kwargs["tools"] == tools
