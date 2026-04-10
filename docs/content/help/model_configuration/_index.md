+++
title = 'Model Configuration Guidance'
weight = 20
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
-->

## Overview

The combined (orchestrator) route in {{< short_app_ref >}} performs classification, sub-session execution, and optional synthesis — all using the configured primary chat model (`ll_model`). This keeps the default configuration simple: a single model handles every stage. Developers building on this application should understand the implications and know where to customize if needed.

## How It Works

When a user query enters the combined route, it passes through up to three LLM call stages:

1. **Classification** — The primary model determines whether the query should be handled by `nl2sql`, `vecsearch`, or `both`. This is a lightweight call with `max_tokens=10` and `temperature=0.0`, designed to return a single word.

2. **Execution** — Based on the classification result, the query is delegated to the appropriate sub-session. When the classification is `both`, the NL2SQL and VecSearch sub-sessions run in parallel.

3. **Synthesis** — When both routes are used and the VecSearch result is deemed relevant, a final LLM call merges the two answers into a single coherent response.

## Considerations for Developers

### Latency and Cost

Classification and synthesis add LLM round-trips that use the primary model. For high-throughput or cost-sensitive workloads, introducing a smaller, dedicated classifier model can reduce both latency and per-request cost for these lightweight calls.

### Model Suitability

Some models may not perform optimally on very short, constrained classification prompts. If classification frequently falls back to `both` (visible in the application logs as a warning), consider evaluating a model better suited for routing tasks.

### Customization Point

The classifier model is derived from the primary `ll_model` configuration at runtime, using the same provider and model ID. This can be customized to use a separate, lighter model for classification and synthesis without affecting the models used by the NL2SQL or VecSearch sub-sessions.

## Fallback Behavior

If classification fails or returns an unexpected value, the system defaults to running both routes. This ensures a response is always returned, even when the classifier encounters an error or produces an unrecognized output.
