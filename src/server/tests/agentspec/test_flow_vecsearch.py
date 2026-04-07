"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Tests for the VecSearch flow definition, WayFlow loading, and session.
"""
# spell-checker: disable

from unittest.mock import AsyncMock, patch

from pyagentspec.flows.nodes import EndNode, LlmNode, StartNode, ToolNode
from pyagentspec.mcp import MCPTool
from pyagentspec.serialization import AgentSpecSerializer

from server.app.agentspec.adapters.litellm import get_litellm_serialization_plugin
from server.app.agentspec.adapters.mcp import build_mcp_transport
from server.app.agentspec.flow_vecsearch import (
    build_vecsearch_flow,
    build_vs_discovery_tool,
    build_vs_grade_tool,
    build_vs_rephrase_tool,
    build_vs_retriever_tool,
)
from server.app.runtime.wayflow.vecsearch import (
    VecSearchFlowSession,
    build_vecsearch_runtime_flow,
)
from server.tests.conftest import (
    MOCK_API_KEY,
    MOCK_SERVER_URL,
    MOCK_SYSTEM_PROMPT,
    SAMPLE_CLIENT_SETTINGS_OBJ,
    assert_flow_basics,
    assert_flow_end_node_has_answer,
    assert_flow_llm_nodes_use_litellm,
)


def _settings_with_toggles(rephrase: bool = True, discovery: bool = True, grade: bool = True):
    """Return a ClientSettings with specified vector_search toggles."""

    base = SAMPLE_CLIENT_SETTINGS_OBJ
    vs = base.vector_search.model_copy(update={"rephrase": rephrase, "discovery": discovery, "grade": grade})
    return base.model_copy(update={"vector_search": vs})


class TestBuildVsTools:
    """Unit tests for MCPTool definitions."""

    def setup_method(self):
        """Create a shared transport for all tool tests."""
        self.transport = build_mcp_transport(MOCK_SERVER_URL, MOCK_API_KEY)

    def test_rephrase_tool_name(self):
        """Verify rephrase tool is named optimizer_vs-rephrase."""
        tool = build_vs_rephrase_tool(self.transport)
        assert isinstance(tool, MCPTool)
        assert tool.name == "optimizer_vs-rephrase"

    def test_rephrase_tool_inputs(self):
        """Verify rephrase tool accepts thread_id, question, and chat_history."""
        tool = build_vs_rephrase_tool(self.transport)
        assert tool.inputs is not None
        input_names = [inp.title for inp in tool.inputs]
        assert "thread_id" in input_names
        assert "question" in input_names
        assert "chat_history" in input_names

    def test_discovery_tool_name(self):
        """Verify discovery tool is named optimizer_vs-discovery."""
        tool = build_vs_discovery_tool(self.transport)
        assert tool.name == "optimizer_vs-discovery"

    def test_discovery_tool_inputs(self):
        """Verify discovery tool accepts thread_id (filter_enabled_models uses MCP default)."""
        tool = build_vs_discovery_tool(self.transport)
        assert tool.inputs is not None
        input_names = [inp.title for inp in tool.inputs]
        assert "thread_id" in input_names
        assert "filter_enabled_models" not in input_names

    def test_retriever_tool_name(self):
        """Verify retriever tool is named optimizer_vs-retriever."""
        tool = build_vs_retriever_tool(self.transport)
        assert tool.name == "optimizer_vs-retriever"

    def test_retriever_tool_inputs(self):
        """Verify retriever tool accepts thread_id and question."""
        tool = build_vs_retriever_tool(self.transport)
        assert tool.inputs is not None
        input_names = [inp.title for inp in tool.inputs]
        assert "thread_id" in input_names
        assert "question" in input_names

    def test_grade_tool_name(self):
        """Verify grade tool is named optimizer_vs-grade."""
        tool = build_vs_grade_tool(self.transport)
        assert tool.name == "optimizer_vs-grade"

    def test_grade_tool_inputs(self):
        """Verify grade tool accepts thread_id, question, and documents."""
        tool = build_vs_grade_tool(self.transport)
        assert tool.inputs is not None
        input_names = [inp.title for inp in tool.inputs]
        assert "thread_id" in input_names
        assert "question" in input_names
        assert "documents" in input_names

    def test_retriever_tool_outputs(self):
        """Verify retriever tool outputs documents only (single output)."""
        tool = build_vs_retriever_tool(self.transport)
        assert tool.outputs is not None
        output_names = [out.title for out in tool.outputs]
        assert output_names == ["documents"]

    def test_tools_share_transport(self):
        """Verify all tools reference the same transport instance."""
        rephrase = build_vs_rephrase_tool(self.transport)
        discovery = build_vs_discovery_tool(self.transport)
        retriever = build_vs_retriever_tool(self.transport)
        grade = build_vs_grade_tool(self.transport)
        assert rephrase.client_transport is self.transport
        assert discovery.client_transport is self.transport
        assert retriever.client_transport is self.transport
        assert grade.client_transport is self.transport


class TestBuildVecsearchFlowAllEnabled:
    """Unit tests for the flow with all toggles enabled."""

    def setup_method(self):
        """Build the VecSearch flow with all toggles on."""
        self.flow = build_vecsearch_flow(
            SAMPLE_CLIENT_SETTINGS_OBJ,
            MOCK_SERVER_URL,
            MOCK_API_KEY,
            MOCK_SYSTEM_PROMPT,
        )

    def test_flow_basics(self):
        """Verify flow type, ID, and name."""
        assert_flow_basics(self.flow, "vecsearch-flow", "VecSearch Flow")

    def test_node_count(self):
        """Verify 7 nodes: start, rephrase, discovery, retriever, grade, LLM, end."""
        assert len(self.flow.nodes) == 7

    def test_has_start_and_end(self):
        """Verify the flow has exactly one StartNode and one EndNode."""
        assert len([n for n in self.flow.nodes if isinstance(n, StartNode)]) == 1
        assert len([n for n in self.flow.nodes if isinstance(n, EndNode)]) == 1

    def test_has_four_tool_nodes(self):
        """Verify 4 ToolNodes: rephrase, discovery, retriever, grade."""
        tool_nodes = [n for n in self.flow.nodes if isinstance(n, ToolNode)]
        assert len(tool_nodes) == 4

    def test_has_one_llm_node(self):
        """Verify 1 LlmNode: format_answer."""
        llm_nodes = [n for n in self.flow.nodes if isinstance(n, LlmNode)]
        assert len(llm_nodes) == 1

    def test_start_node_inputs(self):
        """Verify start node accepts query, thread_id, model, and chat_history."""
        start = self.flow.start_node
        assert start.inputs is not None
        input_names = [inp.title for inp in start.inputs]
        assert set(input_names) == {"query", "thread_id", "model", "chat_history"}

    def test_end_node_has_answer_output(self):
        """Verify end node outputs the answer."""
        assert_flow_end_node_has_answer(self.flow)

    def test_llm_node_uses_litellm_config(self):
        """Verify the LLM node uses LiteLlmConfig."""
        assert_flow_llm_nodes_use_litellm(self.flow)

    def test_system_prompt_in_format_answer(self):
        """Verify the system prompt is embedded in the format_answer prompt template."""
        llm_nodes = [n for n in self.flow.nodes if isinstance(n, LlmNode)]
        assert MOCK_SYSTEM_PROMPT in llm_nodes[0].prompt_template

    def test_flow_serializable_to_json(self):
        """Verify the flow serializes to JSON without error."""
        serializer = AgentSpecSerializer(plugins=[get_litellm_serialization_plugin()])
        json_str = serializer.to_json(self.flow)
        assert json_str is not None
        assert "vecsearch-flow" in json_str

    def test_flow_serializable_to_yaml(self):
        """Verify the flow serializes to YAML without error."""
        serializer = AgentSpecSerializer(plugins=[get_litellm_serialization_plugin()])
        yaml_str = serializer.to_yaml(self.flow)
        assert yaml_str is not None
        assert "VecSearch Flow" in yaml_str


class TestBuildVecsearchFlowNoRephrase:
    """Unit tests for the flow with rephrase disabled."""

    def setup_method(self):
        """Build the VecSearch flow with rephrase=False."""
        settings = _settings_with_toggles(rephrase=False)
        self.flow = build_vecsearch_flow(
            settings,
            MOCK_SERVER_URL,
            MOCK_API_KEY,
            MOCK_SYSTEM_PROMPT,
        )

    def test_node_count(self):
        """Verify 6 nodes: no rephrase node."""
        assert len(self.flow.nodes) == 6

    def test_no_rephrase_node(self):
        """Verify no node named 'rephrase' exists."""
        names = [n.name for n in self.flow.nodes]
        assert "rephrase" not in names

    def test_retriever_still_present(self):
        """Verify the retriever node is always present."""
        names = [n.name for n in self.flow.nodes]
        assert "retriever" in names


class TestBuildVecsearchFlowNoGrade:
    """Unit tests for the flow with grade disabled."""

    def setup_method(self):
        """Build the VecSearch flow with grade=False."""
        settings = _settings_with_toggles(grade=False)
        self.flow = build_vecsearch_flow(
            settings,
            MOCK_SERVER_URL,
            MOCK_API_KEY,
            MOCK_SYSTEM_PROMPT,
        )

    def test_node_count(self):
        """Verify 6 nodes: no grade node."""
        assert len(self.flow.nodes) == 6

    def test_no_grade_node(self):
        """Verify no node named 'grade' exists."""
        names = [n.name for n in self.flow.nodes]
        assert "grade" not in names


class TestBuildVecsearchFlowMinimal:
    """Unit tests for the flow with all optional toggles off."""

    def setup_method(self):
        """Build the VecSearch flow with all toggles off."""
        settings = _settings_with_toggles(rephrase=False, discovery=False, grade=False)
        self.flow = build_vecsearch_flow(
            settings,
            MOCK_SERVER_URL,
            MOCK_API_KEY,
            MOCK_SYSTEM_PROMPT,
        )

    def test_node_count(self):
        """Verify 4 nodes: start, retriever, format_answer, end."""
        assert len(self.flow.nodes) == 4

    def test_only_retriever_tool_node(self):
        """Verify only one ToolNode (retriever) exists."""
        tool_nodes = [n for n in self.flow.nodes if isinstance(n, ToolNode)]
        assert len(tool_nodes) == 1
        assert tool_nodes[0].name == "retriever"

    def test_flow_serializable(self):
        """Verify the minimal flow serializes without error."""
        serializer = AgentSpecSerializer(plugins=[get_litellm_serialization_plugin()])
        json_str = serializer.to_json(self.flow)
        assert json_str is not None


class TestBuildVecsearchRuntimeFlow:
    """Unit tests for WayFlow loading (mocking MCP)."""

    @patch("server.app.runtime.common.fetch_mcp_prompt", new_callable=AsyncMock)
    async def test_returns_runtime_flow(self, mock_fetch):
        """Verify the loader produces a WayFlow runtime flow."""
        mock_fetch.return_value = MOCK_SYSTEM_PROMPT
        flow = await build_vecsearch_runtime_flow(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY)
        assert hasattr(flow, "start_conversation")

    @patch("server.app.runtime.common.fetch_mcp_prompt", new_callable=AsyncMock)
    async def test_uses_mcp_prompt(self, mock_fetch):
        """Verify the loader fetches the optimizer_vs-tools-default prompt."""
        mock_fetch.return_value = "Custom VecSearch prompt."
        await build_vecsearch_runtime_flow(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY)
        mock_fetch.assert_awaited_once_with(MOCK_SERVER_URL, MOCK_API_KEY, "optimizer_vs-tools-default")

    @patch("server.app.runtime.common.fetch_mcp_prompt", new_callable=AsyncMock)
    async def test_fallback_on_mcp_failure(self, mock_fetch):
        """Verify the loader falls back to the default prompt when MCP fails."""
        mock_fetch.side_effect = ConnectionError("MCP server unreachable")
        flow = await build_vecsearch_runtime_flow(SAMPLE_CLIENT_SETTINGS_OBJ, MOCK_SERVER_URL, MOCK_API_KEY)
        assert hasattr(flow, "start_conversation")


class TestGradeRelevantOutput:
    """Tests for the grade_relevant flow output."""

    def test_grade_relevant_in_flow_outputs_all_enabled(self):
        """Verify grade_relevant is a flow-level output when all toggles on."""
        flow = build_vecsearch_flow(
            SAMPLE_CLIENT_SETTINGS_OBJ,
            MOCK_SERVER_URL,
            MOCK_API_KEY,
            MOCK_SYSTEM_PROMPT,
        )
        assert flow.outputs is not None
        output_names = [o.title for o in flow.outputs]
        assert "grade_relevant" in output_names

    def test_grade_relevant_in_end_node_outputs(self):
        """Verify the end node has a grade_relevant output property."""
        flow = build_vecsearch_flow(
            SAMPLE_CLIENT_SETTINGS_OBJ,
            MOCK_SERVER_URL,
            MOCK_API_KEY,
            MOCK_SYSTEM_PROMPT,
        )
        end_nodes = [n for n in flow.nodes if isinstance(n, EndNode)]
        assert len(end_nodes) == 1
        assert end_nodes[0].outputs is not None
        end_output_names = [o.title for o in end_nodes[0].outputs]
        assert "grade_relevant" in end_output_names

    def test_grade_relevant_data_edge_when_grade_enabled(self):
        """Verify a data edge wires grade_node.graded_documents → end.grade_relevant."""
        flow = build_vecsearch_flow(
            _settings_with_toggles(grade=True),
            MOCK_SERVER_URL,
            MOCK_API_KEY,
            MOCK_SYSTEM_PROMPT,
        )
        assert flow.data_flow_connections is not None
        edges = list(flow.data_flow_connections)
        edge = next(
            (e for e in edges if e.name == "grade_to_grade_relevant"),
            None,
        )
        assert edge is not None
        assert edge.source_output == "graded_documents"
        assert edge.destination_input == "grade_relevant"

    def test_no_grade_relevant_data_edge_when_grade_disabled(self):
        """Verify no grade_to_grade_relevant edge when grade is off."""
        flow = build_vecsearch_flow(
            _settings_with_toggles(grade=False),
            MOCK_SERVER_URL,
            MOCK_API_KEY,
            MOCK_SYSTEM_PROMPT,
        )
        edges = flow.data_flow_connections or []
        edge = next(
            (e for e in edges if e.name == "grade_to_grade_relevant"),
            None,
        )
        assert edge is None

    def test_grade_relevant_default_is_yes(self):
        """Verify the grade_relevant property defaults to 'yes'."""
        flow = build_vecsearch_flow(
            _settings_with_toggles(grade=False),
            MOCK_SERVER_URL,
            MOCK_API_KEY,
            MOCK_SYSTEM_PROMPT,
        )
        end_nodes = [n for n in flow.nodes if isinstance(n, EndNode)]
        assert end_nodes[0].outputs is not None
        grade_prop = next(o for o in end_nodes[0].outputs if o.title == "grade_relevant")
        assert grade_prop.default == "yes"


class TestBuildVecsearchFlowDiscoveryOnly:
    """Unit tests for the flow with only discovery enabled."""

    def setup_method(self):
        """Build the VecSearch flow with rephrase=False, discovery=True, grade=False."""
        settings = _settings_with_toggles(rephrase=False, discovery=True, grade=False)
        self.flow = build_vecsearch_flow(settings, MOCK_SERVER_URL, MOCK_API_KEY, MOCK_SYSTEM_PROMPT)

    def test_node_count(self):
        """Verify 5 nodes: start, discovery, retriever, format_answer, end."""
        assert len(self.flow.nodes) == 5

    def test_no_rephrase_no_grade_nodes(self):
        """Verify neither rephrase nor grade nodes exist."""
        names = [n.name for n in self.flow.nodes]
        assert "rephrase" not in names
        assert "grade" not in names

    def test_question_source_is_start(self):
        """Verify retriever gets question from start node, not rephrase."""
        edges = list(self.flow.data_flow_connections or [])
        edge = next(e for e in edges if e.name == "question_to_retriever")
        assert isinstance(edge.source_node, StartNode)
        assert edge.source_output == "query"


class TestBuildVecsearchFlowRephraseDiscovery:
    """Unit tests for the flow with rephrase and discovery enabled, grade disabled."""

    def setup_method(self):
        """Build the VecSearch flow with rephrase=True, discovery=True, grade=False."""
        settings = _settings_with_toggles(rephrase=True, discovery=True, grade=False)
        self.flow = build_vecsearch_flow(settings, MOCK_SERVER_URL, MOCK_API_KEY, MOCK_SYSTEM_PROMPT)

    def test_node_count(self):
        """Verify 6 nodes: start, rephrase, discovery, retriever, format_answer, end."""
        assert len(self.flow.nodes) == 6

    def test_no_grade_node(self):
        """Verify no grade node exists."""
        names = [n.name for n in self.flow.nodes]
        assert "grade" not in names

    def test_question_source_is_rephrase(self):
        """Verify retriever gets question from rephrase node, not start."""
        edges = list(self.flow.data_flow_connections or [])
        edge = next(e for e in edges if e.name == "question_to_retriever")
        assert isinstance(edge.source_node, ToolNode)
        assert edge.source_output == "rephrased_question"


class TestBuildVecsearchFlowDiscoveryGrade:
    """Unit tests for the flow with discovery and grade enabled, rephrase disabled."""

    def setup_method(self):
        """Build the VecSearch flow with rephrase=False, discovery=True, grade=True."""
        settings = _settings_with_toggles(rephrase=False, discovery=True, grade=True)
        self.flow = build_vecsearch_flow(settings, MOCK_SERVER_URL, MOCK_API_KEY, MOCK_SYSTEM_PROMPT)

    def test_node_count(self):
        """Verify 6 nodes: start, discovery, retriever, grade, format_answer, end."""
        assert len(self.flow.nodes) == 6

    def test_no_rephrase_node(self):
        """Verify no rephrase node exists."""
        names = [n.name for n in self.flow.nodes]
        assert "rephrase" not in names

    def test_grade_relevant_output_present(self):
        """Verify the end node has a grade_relevant output."""
        end_nodes = [n for n in self.flow.nodes if isinstance(n, EndNode)]
        assert len(end_nodes) == 1
        assert end_nodes[0].outputs is not None
        output_names = [o.title for o in end_nodes[0].outputs]
        assert "grade_relevant" in output_names


class TestBuildVecsearchFlowRephraseGrade:
    """Unit tests for the flow with rephrase and grade enabled, discovery disabled."""

    def setup_method(self):
        """Build the VecSearch flow with rephrase=True, discovery=False, grade=True."""
        settings = _settings_with_toggles(rephrase=True, discovery=False, grade=True)
        self.flow = build_vecsearch_flow(settings, MOCK_SERVER_URL, MOCK_API_KEY, MOCK_SYSTEM_PROMPT)

    def test_node_count(self):
        """Verify 6 nodes: start, rephrase, retriever, grade, format_answer, end."""
        assert len(self.flow.nodes) == 6

    def test_no_discovery_node(self):
        """Verify no discovery node exists."""
        names = [n.name for n in self.flow.nodes]
        assert "discovery" not in names

    def test_grade_relevant_output_present(self):
        """Verify the end node has a grade_relevant output."""
        end_nodes = [n for n in self.flow.nodes if isinstance(n, EndNode)]
        assert len(end_nodes) == 1
        assert end_nodes[0].outputs is not None
        output_names = [o.title for o in end_nodes[0].outputs]
        assert "grade_relevant" in output_names


def test_vecsearch_session_is_flow_session_subclass():
    """Verify VecSearchFlowSession inherits from FlowSession."""
    from server.app.runtime.wayflow.session import FlowSession

    assert issubclass(VecSearchFlowSession, FlowSession)
