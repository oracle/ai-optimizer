"""
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Integration tests for server/mcp/graph.py orchestration nodes.

Tests the LangGraph node functions including:
- vs_orchestrate (vector search RAG pipeline)
- stream_completion (LLM streaming)
- Graph workflow integration
"""
# pylint: disable=too-few-public-methods

from unittest.mock import MagicMock, patch
import pytest
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from server.mcp.graph import vs_orchestrate


class TestVsOrchestrate:
    """Tests for vs_orchestrate node function."""

    @pytest.fixture
    def mock_config(self):
        """Create mock config for vs_orchestrate."""
        mock_vs = MagicMock()
        mock_vs.rephrase = True
        mock_vs.grade = True

        return {
            "configurable": {"thread_id": "test_thread_123"},
            "metadata": {"vector_search": mock_vs},
        }

    @pytest.fixture
    def base_state(self):
        """Create base state for testing."""
        return {
            "messages": [HumanMessage(content="What are the new features?")],
        }

    @pytest.mark.asyncio
    async def test_vs_orchestrate_successful_retrieval(self, mock_config, base_state):
        """Test successful document retrieval and formatting."""
        # Mock the internal tools
        with (
            patch("server.mcp.graph._vs_rephrase_impl") as mock_rephrase,
            patch("server.mcp.graph._vs_retrieve_impl") as mock_retrieve,
            patch("server.mcp.graph._vs_grade_impl") as mock_grade,
        ):
            # Mock rephrase result
            mock_rephrase_result = MagicMock()
            mock_rephrase_result.status = "success"
            mock_rephrase_result.was_rephrased = True
            mock_rephrase_result.rephrased_prompt = "new features in the system"
            mock_rephrase.return_value = mock_rephrase_result

            # Mock retrieval result
            mock_retrieve_result = MagicMock()
            mock_retrieve_result.status = "success"
            mock_retrieve_result.documents = [
                {"page_content": "Feature A: New dashboard"},
                {"page_content": "Feature B: API improvements"},
            ]
            mock_retrieve_result.searched_tables = ["docs_table"]
            mock_retrieve.return_value = mock_retrieve_result

            # Mock grade result
            mock_grade_result = MagicMock()
            mock_grade_result.status = "success"
            mock_grade_result.relevant = "yes"
            mock_grade_result.formatted_documents = "Feature A: New dashboard\n\nFeature B: API improvements"
            mock_grade.return_value = mock_grade_result

            # Execute
            result = await vs_orchestrate(base_state, mock_config)

            # Verify results
            assert "messages" in result
            assert "vs_metadata" in result

            messages = result["messages"]
            # Should have: cleaned messages + AIMessage with tool_calls + ToolMessage
            assert len(messages) >= 2

            # Find the ToolMessage
            tool_messages = [msg for msg in messages if isinstance(msg, ToolMessage)]
            assert len(tool_messages) == 1

            tool_msg = tool_messages[0]
            assert tool_msg.name == "optimizer_vs-retriever"
            assert tool_msg.tool_call_id == "vs_retriever"

            # Verify vs_metadata
            vs_metadata = result["vs_metadata"]
            assert vs_metadata["num_documents"] == 2
            assert vs_metadata["searched_tables"] == ["docs_table"]
            assert vs_metadata["context_input"] == "new features in the system"

    @pytest.mark.asyncio
    async def test_vs_orchestrate_without_rephrase(self, mock_config, base_state):
        """Test orchestration when rephrase is disabled."""
        # Disable rephrase
        mock_config["metadata"]["vector_search"].rephrase = False

        with (
            patch("server.mcp.graph._vs_retrieve_impl") as mock_retrieve,
            patch("server.mcp.graph._vs_grade_impl") as mock_grade,
        ):
            # Mock retrieval result
            mock_retrieve_result = MagicMock()
            mock_retrieve_result.status = "success"
            mock_retrieve_result.documents = [{"page_content": "Document 1"}]
            mock_retrieve_result.searched_tables = ["table1"]
            mock_retrieve.return_value = mock_retrieve_result

            # Mock grade result
            mock_grade_result = MagicMock()
            mock_grade_result.status = "success"
            mock_grade_result.relevant = "yes"
            mock_grade_result.formatted_documents = "Document 1"
            mock_grade.return_value = mock_grade_result

            # Execute
            _ = await vs_orchestrate(base_state, mock_config)

            # Verify rephrase was NOT called (verify through retrieve args)
            mock_retrieve.assert_called_once()
            call_args = mock_retrieve.call_args
            # Should use original question, not rephrased
            assert call_args[1]["question"] == "What are the new features?"

    @pytest.mark.asyncio
    async def test_vs_orchestrate_without_grade(self, mock_config, base_state):
        """Test orchestration when grading is disabled."""
        # Disable grade
        mock_config["metadata"]["vector_search"].grade = False

        with (
            patch("server.mcp.graph._vs_rephrase_impl") as mock_rephrase,
            patch("server.mcp.graph._vs_retrieve_impl") as mock_retrieve,
        ):
            # Mock rephrase result
            mock_rephrase_result = MagicMock()
            mock_rephrase_result.status = "success"
            mock_rephrase_result.was_rephrased = False
            mock_rephrase_result.rephrased_prompt = "What are the new features?"
            mock_rephrase.return_value = mock_rephrase_result

            # Mock retrieval result
            mock_retrieve_result = MagicMock()
            mock_retrieve_result.status = "success"
            mock_retrieve_result.documents = [
                {"page_content": "Doc 1"},
                {"page_content": "Doc 2"},
            ]
            mock_retrieve_result.searched_tables = ["table1"]
            mock_retrieve.return_value = mock_retrieve_result

            # Execute
            result = await vs_orchestrate(base_state, mock_config)

            # Verify result has all documents (no grading filter)
            tool_messages = [msg for msg in result["messages"] if isinstance(msg, ToolMessage)]
            assert len(tool_messages) == 1
            # Documents should be formatted without grading
            assert result["vs_metadata"]["num_documents"] == 2

    @pytest.mark.asyncio
    async def test_vs_orchestrate_retrieval_failure(self, mock_config, base_state):
        """Test handling of retrieval failure."""
        with (
            patch("server.mcp.graph._vs_rephrase_impl") as mock_rephrase,
            patch("server.mcp.graph._vs_retrieve_impl") as mock_retrieve,
        ):
            # Mock rephrase success
            mock_rephrase_result = MagicMock()
            mock_rephrase_result.status = "success"
            mock_rephrase_result.was_rephrased = False
            mock_rephrase_result.rephrased_prompt = "What are the new features?"
            mock_rephrase.return_value = mock_rephrase_result

            # Mock retrieval failure
            mock_retrieve_result = MagicMock()
            mock_retrieve_result.status = "error"
            mock_retrieve_result.error = "Database connection failed"
            mock_retrieve.return_value = mock_retrieve_result

            # Execute
            result = await vs_orchestrate(base_state, mock_config)

            # Should return error message
            tool_messages = [msg for msg in result["messages"] if isinstance(msg, ToolMessage)]
            assert len(tool_messages) == 1
            assert "Vector search retrieval failed" in tool_messages[0].content

    @pytest.mark.asyncio
    async def test_vs_orchestrate_documents_graded_not_relevant(self, mock_config, base_state):
        """Test when documents are graded as not relevant."""
        with (
            patch("server.mcp.graph._vs_rephrase_impl") as mock_rephrase,
            patch("server.mcp.graph._vs_retrieve_impl") as mock_retrieve,
            patch("server.mcp.graph._vs_grade_impl") as mock_grade,
        ):
            # Mock rephrase
            mock_rephrase_result = MagicMock()
            mock_rephrase_result.status = "success"
            mock_rephrase_result.was_rephrased = False
            mock_rephrase_result.rephrased_prompt = "What are the new features?"
            mock_rephrase.return_value = mock_rephrase_result

            # Mock retrieval with documents
            mock_retrieve_result = MagicMock()
            mock_retrieve_result.status = "success"
            mock_retrieve_result.documents = [{"page_content": "Irrelevant doc"}]
            mock_retrieve_result.searched_tables = ["table1"]
            mock_retrieve.return_value = mock_retrieve_result

            # Mock grade as NOT relevant
            mock_grade_result = MagicMock()
            mock_grade_result.status = "success"
            mock_grade_result.relevant = "no"  # Not relevant
            mock_grade_result.formatted_documents = ""
            mock_grade.return_value = mock_grade_result

            # Execute
            result = await vs_orchestrate(base_state, mock_config)

            # Should still return ToolMessage but with "no relevant documents"
            tool_messages = [msg for msg in result["messages"] if isinstance(msg, ToolMessage)]
            assert len(tool_messages) == 1
            assert "No relevant documents found" in tool_messages[0].content

    @pytest.mark.asyncio
    async def test_vs_orchestrate_with_chat_history(self, mock_config):
        """Test that chat history is passed to rephrase correctly."""
        # State with conversation history
        state = {
            "messages": [
                HumanMessage(content="What is the product?"),
                AIMessage(content="It's a RAG application."),
                HumanMessage(content="Tell me more"),  # Vague follow-up
            ]
        }

        with (
            patch("server.mcp.graph._vs_rephrase_impl") as mock_rephrase,
            patch("server.mcp.graph._vs_retrieve_impl") as mock_retrieve,
            patch("server.mcp.graph._vs_grade_impl") as mock_grade,
        ):
            # Mock all tools
            mock_rephrase_result = MagicMock()
            mock_rephrase_result.status = "success"
            mock_rephrase_result.was_rephrased = True
            mock_rephrase_result.rephrased_prompt = "Tell me more about the RAG application"
            mock_rephrase.return_value = mock_rephrase_result

            mock_retrieve_result = MagicMock()
            mock_retrieve_result.status = "success"
            mock_retrieve_result.documents = [{"page_content": "Details about RAG"}]
            mock_retrieve_result.searched_tables = ["docs"]
            mock_retrieve.return_value = mock_retrieve_result

            mock_grade_result = MagicMock()
            mock_grade_result.status = "success"
            mock_grade_result.relevant = "yes"
            mock_grade_result.formatted_documents = "Details about RAG"
            mock_grade.return_value = mock_grade_result

            # Execute
            await vs_orchestrate(state, mock_config)

            # Verify rephrase was called with chat history
            mock_rephrase.assert_called_once()
            call_args = mock_rephrase.call_args
            assert call_args[1]["question"] == "Tell me more"
            # Should have chat history
            assert call_args[1]["chat_history"] is not None
            assert len(call_args[1]["chat_history"]) == 2  # Previous Q&A pair


class TestVsOrchestrateMessageHandling:
    """Tests for message handling in vs_orchestrate."""

    @pytest.mark.asyncio
    async def test_removes_old_tool_messages(self):
        """Test that old ToolMessages are removed before orchestration."""
        # State with previous tool messages
        old_tool_msg = ToolMessage(content="Old result", tool_call_id="old_call")
        old_ai_msg = AIMessage(content="", tool_calls=[{"id": "old_call", "name": "old_tool", "args": {}}])

        state = {
            "messages": [
                HumanMessage(content="First question"),
                old_ai_msg,
                old_tool_msg,
                HumanMessage(content="New question"),
            ]
        }

        mock_config = {
            "configurable": {"thread_id": "test_thread"},
            "metadata": {"vector_search": MagicMock(rephrase=False, grade=False)},
        }

        with patch("server.mcp.graph._vs_retrieve_impl") as mock_retrieve:
            mock_retrieve_result = MagicMock()
            mock_retrieve_result.status = "success"
            mock_retrieve_result.documents = []
            mock_retrieve_result.searched_tables = []
            mock_retrieve.return_value = mock_retrieve_result

            result = await vs_orchestrate(state, mock_config)

            # Verify old tool messages are not in result
            result_messages = result["messages"]
            for msg in result_messages:
                if isinstance(msg, ToolMessage):
                    assert msg.tool_call_id != "old_call"
