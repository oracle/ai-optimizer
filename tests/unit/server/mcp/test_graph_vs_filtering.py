"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Unit tests for graph.py vector search message filtering.

Tests that internal VS ToolMessages are properly filtered when grading
determines documents are not relevant.
"""

import json
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage

from server.mcp.graph import _prepare_messages_for_completion


class TestPrepareMessagesForCompletion:
    """Tests for _prepare_messages_for_completion function."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config with system prompt."""
        mock_prompt = MagicMock()
        mock_prompt.content.text = "You are a helpful assistant."

        config = {
            "metadata": {
                "sys_prompt": mock_prompt,
                "use_history": True,
            }
        }
        return config

    @pytest.fixture
    def internal_vs_tool_message(self):
        """Create an internal VS ToolMessage (marked with internal_vs=True)."""
        documents = [
            {"page_content": "Document 1 content about new features"},
            {"page_content": "Document 2 content about updates"},
        ]
        return ToolMessage(
            content=json.dumps({
                "documents": documents,
                "context_input": "new features"
            }),
            tool_call_id="call_123",
            name="optimizer_vs-retriever",
            additional_kwargs={"internal_vs": True},
        )

    @pytest.fixture
    def external_tool_message(self):
        """Create an external ToolMessage (NOT internal_vs)."""
        return ToolMessage(
            content="External tool result",
            tool_call_id="call_456",
            name="external_tool",
        )

    def test_internal_vs_toolmessage_content_minimized(
        self, mock_config, internal_vs_tool_message
    ):
        """Test that internal_vs ToolMessages have content minimized (not full documents).

        This simulates the scenario where:
        1. User asks follow-up question like "tell me more"
        2. VS retrieval returns documents
        3. Grading determines documents are NOT relevant (state["documents"] = "")
        4. The internal_vs ToolMessage should have minimal content (not full documents)

        The ToolMessage is kept (to satisfy OpenAI API contract - tool_calls need responses)
        but its content is minimized to prevent context bloat. Documents are injected
        via system prompt when relevant, not via ToolMessage content.
        """
        # Create state simulating grading returned "not relevant"
        # - documents is empty (grading said not relevant)
        # - but messages still contains the internal_vs ToolMessage with full doc content
        ai_with_tool_call = AIMessage(
            content="",
            tool_calls=[{
                "id": "call_123",
                "name": "optimizer_vs-retriever",
                "args": {"question": "tell me more"}
            }]
        )

        state = {
            "messages": [
                HumanMessage(content="What are the new features?"),
                AIMessage(content="Here are the new features..."),
                HumanMessage(content="tell me more"),
                ai_with_tool_call,
                internal_vs_tool_message,  # Has full document content
            ],
            "cleaned_messages": [
                HumanMessage(content="tell me more"),
            ],
            "documents": "",  # Empty - grading said not relevant
            "context_input": "",  # Empty - grading said not relevant
        }

        # Call the function under test
        result = _prepare_messages_for_completion(state, mock_config)

        # Assert: internal_vs ToolMessage should be present but with minimal content
        tool_messages = [msg for msg in result if isinstance(msg, ToolMessage)]
        internal_vs_messages = [
            msg for msg in tool_messages
            if msg.additional_kwargs.get("internal_vs", False)
        ]

        # ToolMessage should still exist (satisfies API contract)
        assert len(internal_vs_messages) == 1, (
            "Internal VS ToolMessage should be present (for API contract)"
        )

        # But content should be minimized - reports "no relevant docs" since state["documents"] is empty
        msg_content = internal_vs_messages[0].content
        expected_content = '{"status": "success", "result": "No relevant documents found for this query."}'
        assert msg_content == expected_content, (
            f"Internal VS ToolMessage content should report no relevant docs, got: {msg_content}"
        )

        # Verify original documents are NOT in the content sent to LLM
        assert "Document 1 content" not in msg_content
        assert "Document 2 content" not in msg_content

    def test_external_toolmessages_preserved(
        self, mock_config, external_tool_message
    ):
        """Test that external (non-VS) ToolMessages are NOT filtered.

        External tools should always have their ToolMessages preserved in the
        conversation, as the LLM needs to see the results.
        """
        ai_with_tool_call = AIMessage(
            content="",
            tool_calls=[{
                "id": "call_456",
                "name": "external_tool",
                "args": {}
            }]
        )

        state = {
            "messages": [
                HumanMessage(content="Use the external tool"),
                ai_with_tool_call,
                external_tool_message,  # This should be preserved
            ],
            "cleaned_messages": [
                HumanMessage(content="Use the external tool"),
            ],
            "documents": "",
            "context_input": "",
        }

        result = _prepare_messages_for_completion(state, mock_config)

        # Assert: external ToolMessage should be preserved
        tool_messages = [msg for msg in result if isinstance(msg, ToolMessage)]
        assert len(tool_messages) == 1, "External ToolMessage should be preserved"
        assert tool_messages[0].name == "external_tool"

    def test_internal_vs_minimized_but_external_preserved(
        self, mock_config, internal_vs_tool_message, external_tool_message
    ):
        """Test mixed scenario: internal_vs content minimized, external content preserved."""
        ai_with_vs_call = AIMessage(
            content="",
            tool_calls=[{
                "id": "call_123",
                "name": "optimizer_vs-retriever",
                "args": {"question": "tell me more"}
            }]
        )
        ai_with_external_call = AIMessage(
            content="",
            tool_calls=[{
                "id": "call_456",
                "name": "external_tool",
                "args": {}
            }]
        )

        state = {
            "messages": [
                HumanMessage(content="Query with both tools"),
                ai_with_vs_call,
                internal_vs_tool_message,  # Content should be minimized
                ai_with_external_call,
                external_tool_message,  # Content should be preserved
            ],
            "cleaned_messages": [
                HumanMessage(content="Query with both tools"),
            ],
            "documents": "",  # Grading said not relevant
            "context_input": "",
        }

        result = _prepare_messages_for_completion(state, mock_config)

        tool_messages = [msg for msg in result if isinstance(msg, ToolMessage)]

        # Should have both tool messages
        assert len(tool_messages) == 2, (
            f"Expected 2 tool messages, got {len(tool_messages)}"
        )

        # Find each by name
        internal_vs_msg = next(m for m in tool_messages if m.name == "optimizer_vs-retriever")
        external_msg = next(m for m in tool_messages if m.name == "external_tool")

        # Internal VS content should report no relevant docs (state["documents"] is empty)
        expected_content = '{"status": "success", "result": "No relevant documents found for this query."}'
        assert internal_vs_msg.content == expected_content, (
            f"Internal VS content should report no relevant docs, got: {internal_vs_msg.content}"
        )

        # External tool content should be preserved
        assert external_msg.content == "External tool result", (
            f"External tool content should be preserved, got: {external_msg.content}"
        )

    def test_documents_injected_when_relevant(self, mock_config):
        """Test that documents ARE injected into system prompt when grading says relevant.

        When grading determines documents ARE relevant:
        - state["documents"] contains the formatted documents
        - Documents should be appended to system prompt
        """
        state = {
            "messages": [
                HumanMessage(content="What are the new features?"),
            ],
            "cleaned_messages": [
                HumanMessage(content="What are the new features?"),
            ],
            "documents": "Document 1: New feature A\nDocument 2: New feature B",
            "context_input": "new features",
        }

        result = _prepare_messages_for_completion(state, mock_config)

        # System prompt should contain the documents
        system_messages = [msg for msg in result if isinstance(msg, SystemMessage)]
        assert len(system_messages) == 1

        system_content = system_messages[0].content
        assert "Relevant Context:" in system_content
        assert "Document 1: New feature A" in system_content
        assert "Document 2: New feature B" in system_content

    def test_no_documents_injected_when_not_relevant(self, mock_config):
        """Test that documents are NOT injected when grading says not relevant."""
        state = {
            "messages": [
                HumanMessage(content="tell me more"),
            ],
            "cleaned_messages": [
                HumanMessage(content="tell me more"),
            ],
            "documents": "",  # Empty - grading said not relevant
            "context_input": "",
        }

        result = _prepare_messages_for_completion(state, mock_config)

        # System prompt should NOT contain "Relevant Context:"
        system_messages = [msg for msg in result if isinstance(msg, SystemMessage)]
        assert len(system_messages) == 1

        system_content = system_messages[0].content
        assert "Relevant Context:" not in system_content

    def test_toolmessage_content_when_docs_relevant(
        self, mock_config, internal_vs_tool_message
    ):
        """Test ToolMessage content reports success when documents ARE relevant."""
        ai_with_tool_call = AIMessage(
            content="",
            tool_calls=[{
                "id": "call_123",
                "name": "optimizer_vs-retriever",
                "args": {"question": "new features"}
            }]
        )

        state = {
            "messages": [
                HumanMessage(content="What are the new features?"),
                ai_with_tool_call,
                internal_vs_tool_message,
            ],
            "cleaned_messages": [
                HumanMessage(content="What are the new features?"),
            ],
            "documents": "Document 1: New feature A\nDocument 2: New feature B",
            "context_input": "new features",
        }

        result = _prepare_messages_for_completion(state, mock_config)

        tool_messages = [msg for msg in result if isinstance(msg, ToolMessage)]
        internal_vs_messages = [
            msg for msg in tool_messages
            if msg.additional_kwargs.get("internal_vs", False)
        ]

        assert len(internal_vs_messages) == 1
        expected_content = '{"status": "success", "result": "Relevant documents found and added to context."}'
        assert internal_vs_messages[0].content == expected_content
