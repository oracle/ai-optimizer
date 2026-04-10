"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

VecSearch Flow — AgentSpec definition for vector similarity search.

Defines a Flow with build-time conditional topology based on client_settings:
- rephrase (optional): Rephrase the query using chat history
- discovery (optional): Discover available vector storage tables
- retriever (always): Perform vector similarity search
- grade (optional): Grade document relevance
- LLM answer (always): Generate a natural language answer

All components are pyagentspec SDK classes. No runtime imports.
"""
# spell-checker: ignore pyagentspec streamable agentspec controlflowedge dataflowedge vecsearch

from dataclasses import dataclass, field
from typing import Any, List, cast

from pyagentspec.flows.edges.controlflowedge import ControlFlowEdge
from pyagentspec.flows.edges.dataflowedge import DataFlowEdge
from pyagentspec.flows.flow import Flow
from pyagentspec.flows.nodes import EndNode, LlmNode, StartNode, ToolNode
from pyagentspec.mcp import MCPTool, StreamableHTTPTransport
from pyagentspec.property import Property, StringProperty

from server.app.agentspec.adapters.mcp import build_mcp_transport
from server.app.agentspec.agent_llm_only import build_llm_config
from server.app.core.schemas import ClientSettings


def build_end_node_with_answer(
    prev_node: LlmNode,
    control_edges: List[ControlFlowEdge],
    data_edges: List[DataFlowEdge],
    output_name: str = "answer",
    end_name: str = "end",
    extra_outputs: List[Any] | None = None,
) -> EndNode:
    """Create an EndNode wired to receive output from the previous node."""

    outputs: List[Any] = [StringProperty(title=output_name)]
    if extra_outputs:
        outputs.extend(extra_outputs)
    end = EndNode(name=end_name, outputs=outputs)
    control_edges.append(ControlFlowEdge(name=f"to_{end_name}", from_node=prev_node, to_node=end))
    data_edges.append(
        DataFlowEdge(
            name=f"{output_name}_to_{end_name}",
            source_node=prev_node,
            source_output="answer",
            destination_node=end,
            destination_input=output_name,
        ),
    )
    return end


def build_format_answer_node(
    llm_config: Any,
    prompt_template: str,
    inputs: List[Any],
) -> LlmNode:
    """Create the format_answer LlmNode with the given prompt and inputs."""

    return LlmNode(
        name="format_answer",
        llm_config=llm_config,
        prompt_template=prompt_template,
        inputs=inputs,
        outputs=[StringProperty(title="answer")],
    )


def build_standard_inputs(include_connection: bool = False) -> List[Property]:
    """Return the standard input properties shared across flows."""

    base_inputs = cast(
        List[Property],
        [
            StringProperty(title="query"),
            StringProperty(title="thread_id"),
            StringProperty(title="model"),
            StringProperty(title="chat_history"),
        ],
    )
    if include_connection:
        base_inputs = [*base_inputs, StringProperty(title="connection_name")]
    return base_inputs


def assemble_flow(
    flow_id: str,
    flow_name: str,
    description: str,
    start: StartNode,
    nodes: List[Any],
    control_edges: List[ControlFlowEdge],
    data_edges: List[DataFlowEdge],
    inputs: List[Any],
    outputs: List[Any] | None = None,
) -> Flow:
    """Assemble a Flow with configurable outputs (defaults to 'answer')."""

    return Flow(
        id=flow_id,
        name=flow_name,
        description=description,
        start_node=start,
        nodes=nodes,
        control_flow_connections=control_edges,
        data_flow_connections=data_edges,
        inputs=inputs,
        outputs=outputs or [StringProperty(title="answer")],
    )


def build_vs_rephrase_tool(transport: StreamableHTTPTransport) -> MCPTool:
    """Define the optimizer_vs-rephrase MCPTool."""
    return MCPTool(
        name="optimizer_vs-rephrase",
        description="Rephrase a question using conversation history for better retrieval.",
        client_transport=transport,
        inputs=[
            StringProperty(title="thread_id"),
            StringProperty(title="question"),
            StringProperty(title="chat_history"),
        ],
        outputs=[StringProperty(title="rephrased_question")],
    )


def build_vs_discovery_tool(transport: StreamableHTTPTransport) -> MCPTool:
    """Define the optimizer_vs-discovery MCPTool."""
    return MCPTool(
        name="optimizer_vs-discovery",
        description="List available vector storage tables.",
        client_transport=transport,
        inputs=[
            StringProperty(title="thread_id"),
        ],
        outputs=[StringProperty(title="discovery_result")],
    )


def build_vs_retriever_tool(transport: StreamableHTTPTransport) -> MCPTool:
    """Define the optimizer_vs-retriever MCPTool."""
    return MCPTool(
        name="optimizer_vs-retriever",
        description="Perform vector similarity search to retrieve relevant documents.",
        client_transport=transport,
        inputs=[
            StringProperty(title="thread_id"),
            StringProperty(title="question"),
        ],
        outputs=[StringProperty(title="documents")],
    )


def build_vs_grade_tool(transport: StreamableHTTPTransport) -> MCPTool:
    """Define the optimizer_vs-grade MCPTool."""
    return MCPTool(
        name="optimizer_vs-grade",
        description="Grade the relevance of retrieved documents to the question.",
        client_transport=transport,
        inputs=[
            StringProperty(title="thread_id"),
            StringProperty(title="question"),
            StringProperty(title="documents"),
        ],
        outputs=[StringProperty(title="graded_documents")],
    )


@dataclass
class _FlowState:
    """Mutable state accumulated while building the VecSearch flow topology."""

    start: StartNode
    nodes: list[Any] = field(default_factory=list)
    control_edges: List[ControlFlowEdge] = field(default_factory=list)
    data_edges: List[DataFlowEdge] = field(default_factory=list)
    prev_node: StartNode | ToolNode | LlmNode = field(init=False)
    question_source_node: StartNode | ToolNode = field(init=False)
    question_source_output: str = "query"

    def __post_init__(self) -> None:
        self.nodes.append(self.start)
        self.prev_node = self.start
        self.question_source_node = self.start


def _add_rephrase(state: _FlowState, transport: StreamableHTTPTransport) -> None:
    """Add the optional rephrase node to the flow."""
    rephrase_node = ToolNode(name="rephrase", tool=build_vs_rephrase_tool(transport))
    state.nodes.append(rephrase_node)
    state.control_edges.append(ControlFlowEdge(name="to_rephrase", from_node=state.prev_node, to_node=rephrase_node))
    state.data_edges.extend(
        [
            DataFlowEdge(
                name="start_query_to_rephrase",
                source_node=state.start,
                source_output="query",
                destination_node=rephrase_node,
                destination_input="question",
            ),
            DataFlowEdge(
                name="start_chat_history_to_rephrase",
                source_node=state.start,
                source_output="chat_history",
                destination_node=rephrase_node,
                destination_input="chat_history",
            ),
            DataFlowEdge(
                name="start_thread_to_rephrase",
                source_node=state.start,
                source_output="thread_id",
                destination_node=rephrase_node,
                destination_input="thread_id",
            ),
        ]
    )
    state.prev_node = rephrase_node
    state.question_source_node = rephrase_node
    state.question_source_output = "rephrased_question"


def _add_discovery(state: _FlowState, transport: StreamableHTTPTransport) -> None:
    """Add the optional discovery node to the flow."""
    discovery_node = ToolNode(name="discovery", tool=build_vs_discovery_tool(transport))
    state.nodes.append(discovery_node)
    state.control_edges.append(ControlFlowEdge(name="to_discovery", from_node=state.prev_node, to_node=discovery_node))
    state.data_edges.append(
        DataFlowEdge(
            name="start_thread_to_discovery",
            source_node=state.start,
            source_output="thread_id",
            destination_node=discovery_node,
            destination_input="thread_id",
        ),
    )
    state.prev_node = discovery_node


def _add_retriever(state: _FlowState, transport: StreamableHTTPTransport) -> ToolNode:
    """Add the retriever node (always present) and return it."""
    retriever_node = ToolNode(name="retriever", tool=build_vs_retriever_tool(transport))
    state.nodes.append(retriever_node)
    state.control_edges.append(ControlFlowEdge(name="to_retriever", from_node=state.prev_node, to_node=retriever_node))
    state.data_edges.extend(
        [
            DataFlowEdge(
                name="question_to_retriever",
                source_node=state.question_source_node,
                source_output=state.question_source_output,
                destination_node=retriever_node,
                destination_input="question",
            ),
            DataFlowEdge(
                name="start_thread_to_retriever",
                source_node=state.start,
                source_output="thread_id",
                destination_node=retriever_node,
                destination_input="thread_id",
            ),
        ]
    )
    state.prev_node = retriever_node
    return retriever_node


def _add_grade(state: _FlowState, transport: StreamableHTTPTransport, retriever_node: ToolNode) -> tuple:
    """Add the optional grade node. Returns (documents_source_node, documents_source_output)."""
    grade_node = ToolNode(name="grade", tool=build_vs_grade_tool(transport))
    state.nodes.append(grade_node)
    state.control_edges.append(ControlFlowEdge(name="to_grade", from_node=state.prev_node, to_node=grade_node))
    state.data_edges.extend(
        [
            DataFlowEdge(
                name="question_to_grade",
                source_node=state.question_source_node,
                source_output=state.question_source_output,
                destination_node=grade_node,
                destination_input="question",
            ),
            DataFlowEdge(
                name="documents_to_grade",
                source_node=retriever_node,
                source_output="documents",
                destination_node=grade_node,
                destination_input="documents",
            ),
            DataFlowEdge(
                name="start_thread_to_grade",
                source_node=state.start,
                source_output="thread_id",
                destination_node=grade_node,
                destination_input="thread_id",
            ),
        ]
    )
    state.prev_node = grade_node
    return grade_node, "graded_documents"


def build_vecsearch_flow(
    client_settings: ClientSettings,
    server_url: str,
    api_key: str,
    system_prompt: str,
    output_name: str = "answer",
    flow_id: str = "vecsearch-flow",
) -> Flow:
    """Build the VecSearch AgentSpec Flow.

    The flow topology is determined at build time based on
    client_settings.vector_search toggles (rephrase, discovery, grade).

    Parameters
    ----------
    client_settings:
        The ClientSettings object containing ll_model and vector_search config.
    server_url:
        MCP server URL for tool transport.
    api_key:
        API key for MCP server auth.
    system_prompt:
        System prompt to embed in the LLM node prompt template.

    Returns
    -------
    Flow
        A pyagentspec Flow ready to be serialized or loaded into WayFlow.
    """
    llm_config = build_llm_config(client_settings)
    transport = build_mcp_transport(server_url, api_key)

    vs_settings = client_settings.vector_search

    start = StartNode(name="start", inputs=build_standard_inputs())
    state = _FlowState(start)

    if vs_settings.rephrase:
        _add_rephrase(state, transport)
    if vs_settings.discovery:
        _add_discovery(state, transport)

    retriever_node = _add_retriever(state, transport)

    docs_source_node: ToolNode = retriever_node
    docs_source_output = "documents"
    if vs_settings.grade:
        docs_source_node, docs_source_output = _add_grade(state, transport, retriever_node)

    # --- Format Answer LLM ---

    format_answer_node = build_format_answer_node(
        llm_config=llm_config,
        prompt_template=(
            f"{system_prompt}\n\n"
            "User question: {{question}}\n"
            "Retrieved documents:\n{{documents}}\n\n"
            "Provide a clear, natural language answer to the user's question "
            "based on the retrieved documents."
        ),
        inputs=[
            StringProperty(title="question"),
            StringProperty(title="documents"),
        ],
    )
    state.nodes.append(format_answer_node)

    state.control_edges.append(
        ControlFlowEdge(name="to_format_answer", from_node=state.prev_node, to_node=format_answer_node)
    )
    state.data_edges.extend(
        [
            DataFlowEdge(
                name="question_to_format",
                source_node=state.question_source_node,
                source_output=state.question_source_output,
                destination_node=format_answer_node,
                destination_input="question",
            ),
            DataFlowEdge(
                name="documents_to_format",
                source_node=docs_source_node,
                source_output=docs_source_output,
                destination_node=format_answer_node,
                destination_input="documents",
            ),
        ]
    )

    # --- End ---

    end = build_end_node_with_answer(
        format_answer_node,
        state.control_edges,
        state.data_edges,
        output_name=output_name,
        extra_outputs=[
            StringProperty(title="vs_metadata"),
            StringProperty(title="grade_relevant", default="yes"),
        ],
    )
    state.data_edges.append(
        DataFlowEdge(
            name="docs_to_vs_metadata",
            source_node=retriever_node,
            source_output="documents",
            destination_node=end,
            destination_input="vs_metadata",
        ),
    )
    if vs_settings.grade:
        state.data_edges.append(
            DataFlowEdge(
                name="grade_to_grade_relevant",
                source_node=docs_source_node,
                source_output="graded_documents",
                destination_node=end,
                destination_input="grade_relevant",
            )
        )
    state.nodes.append(end)

    return assemble_flow(
        flow_id=flow_id,
        flow_name="VecSearch Flow",
        description="Performs vector similarity search with optional rephrase, discovery, and grading.",
        start=start,
        nodes=state.nodes,
        control_edges=state.control_edges,
        data_edges=state.data_edges,
        inputs=build_standard_inputs(),
        outputs=[
            StringProperty(title=output_name),
            StringProperty(title="vs_metadata"),
            StringProperty(title="grade_relevant"),
        ],
    )
