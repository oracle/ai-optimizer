"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Shared helpers
"""
# spell-checker: disable

import urllib.error
import urllib.request
from typing import cast

from pyagentspec.flows.edges.controlflowedge import ControlFlowEdge
from pyagentspec.flows.edges.dataflowedge import DataFlowEdge
from pyagentspec.flows.flow import Flow
from pyagentspec.flows.nodes import EndNode, LlmNode, StartNode
from pyagentspec.property import StringProperty
from wayflowcore.agentspec.runtimeloader import AgentSpecLoader
from wayflowcore.flow import Flow as RuntimeFlow

from server.app.agentspec.adapters.litellm import LiteLlmConfig
from server.app.agentspec.flow_vecsearch import assemble_flow, build_standard_inputs
from server.app.runtime.wayflow.adapters.litellm import get_litellm_wayflow_plugin


def ollama_available() -> bool:
    """Return True if ollama is reachable at the default endpoint."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434", timeout=2):
            pass
        return True
    except (urllib.error.URLError, OSError):
        return False


def build_minimal_test_flow(
    *,
    llm_node_name: str = "format_answer",
    flow_id: str = "test-flow",
    flow_name: str = "Test Flow",
    description: str = "Minimal flow for integration tests",
) -> Flow:
    """Build a minimal AgentSpec flow: Start -> LlmNode -> End.

    Parameters
    ----------
    llm_node_name:
        Name for the LlmNode step (e.g. ``"format_answer"``).
    flow_id, flow_name, description:
        Metadata for the flow.
    """
    llm_config = LiteLlmConfig(
        name="test-litellm",
        provider="ollama",
        model_id="qwen3:8b",
        api_base="http://127.0.0.1:11434",
        max_tokens=512,
    )

    inputs = build_standard_inputs()

    start = StartNode(name="start", inputs=inputs)

    llm_node = LlmNode(
        name=llm_node_name,
        llm_config=llm_config,
        prompt_template="Answer briefly: {{query}}",
        inputs=[StringProperty(title="query")],
        outputs=[StringProperty(title="answer")],
    )

    end = EndNode(name="end", outputs=[StringProperty(title="answer")])

    control_edges = [
        ControlFlowEdge(name="start_to_llm", from_node=start, to_node=llm_node),
        ControlFlowEdge(name="llm_to_end", from_node=llm_node, to_node=end),
    ]

    data_edges = [
        DataFlowEdge(
            name="query_to_llm",
            source_node=start,
            source_output="query",
            destination_node=llm_node,
            destination_input="query",
        ),
        DataFlowEdge(
            name="answer_to_end",
            source_node=llm_node,
            source_output="answer",
            destination_node=end,
            destination_input="answer",
        ),
    ]

    return assemble_flow(
        flow_id=flow_id,
        flow_name=flow_name,
        description=description,
        start=start,
        nodes=[start, llm_node, end],
        control_edges=control_edges,
        data_edges=data_edges,
        inputs=inputs,
    )


def load_test_flow(**kwargs) -> RuntimeFlow:
    """Build and load a minimal test flow into WayFlow runtime."""
    agentspec_flow = build_minimal_test_flow(**kwargs)
    loader = AgentSpecLoader(plugins=[get_litellm_wayflow_plugin()])
    return cast(RuntimeFlow, loader.load_component(agentspec_flow))


# ---------------------------------------------------------------------------
# Mock streaming chunk factories  (re-exported from shared_helpers)
# ---------------------------------------------------------------------------

# NOTE: make_stream_chunk, make_usage_chunk, async_iter, drain_queue have been
# moved to server.tests.runtime.shared_helpers.  Import directly from there.
