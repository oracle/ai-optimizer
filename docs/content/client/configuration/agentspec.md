+++
title = "🧬 AgentSpec Definitions"
weight = 60
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore agentspec pyagentspec
-->

The {{< full_app_ref >}} exposes portable [AgentSpec]({{% relref "/agents" %}}) definitions that describe agent pipelines as serializable JSON. These definitions can be inspected in the GUI, customized, and loaded into any compatible runtime.

## Built-in Specifications

The {{< short_app_ref >}} provides three built-in AgentSpec definitions:

| Name | Type | Description |
|------|------|-------------|
| `llm_only` | Agent | LLM-only conversational agent with no tools |
| `nl2sql_agent` | Agent | NL2SQL agent with dynamic MCP tool discovery |
| `vecsearch_flow` | Flow | RAG pipeline: rephrase, retrieve, grade, answer |

## Viewing Specifications

Navigate to the **Configuration** page and select the **AgentSpec** tab.

Each specification is listed with its name and description. Click the **Details** button to view the full serialized JSON definition. This JSON represents the complete AgentSpec that is built from the current sample configuration and can be used as a starting point for custom agent definitions.

For more information on the agent architecture and how these specifications are used at runtime, see the [Agents]({{% relref "/agents" %}}) documentation.
