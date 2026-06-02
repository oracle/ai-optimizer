+++
title = 'Reading Traces'
weight = 20
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore signoz openinference langgraph oitracer
-->

Once telemetry is flowing into a backend, the question becomes: what do you *do* with it? This page covers the practical workflow for using traces and correlated logs to understand the {{% short_app_ref %}} server's behavior — debugging requests, watching production health, and reasoning about LLM cost.

The screenshots and view names below are from [SigNoz]({{% relref "/observability/signoz" %}}). The same data is available in any OTLP backend; only the UI navigation differs.

## Generate a Representative Trace

`GET /v1/healthz` is enough to verify the pipe but does not exercise the agent. To produce a useful trace, send a real chat request through the application — either through the Streamlit UI or via the API:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "X-API-Key: $AIO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"What is Oracle Database?"}]}'
```

Within a few seconds, the trace appears in SigNoz under **Traces → service: `ai-optimizer-server`**. Sort by duration descending and the chat trace is the longest one near the top of the list.

## Reading a Flame Graph

Open a chat trace. SigNoz renders the spans as a flame graph (waterfall):

- **Each horizontal bar is a span** — a unit of work.
- **Bar width is duration** — wider = slower.
- **Indentation shows parent/child** — a span sitting under another span happened *inside* it.
- **The order top-to-bottom is roughly time-ordered** — what happened first sits highest.

A typical chat trace looks like:

```
POST /v1/chat/completions                            SERVER     5.4s
└── LangGraph: invoke                                INTERNAL   5.3s
    ├── retrieve_documents                           INTERNAL   180ms
    │   └── HTTP POST oracledb-vector-search         CLIENT     175ms
    ├── format_prompt                                INTERNAL   3ms
    └── ChatLiteLLM.invoke                           LLM        5.0s   ← read this span
        └── HTTP POST api.openai.com/v1/chat/...     CLIENT     4.95s
```

Reading the graph tells you immediately:

- The whole request took **5.4 seconds**.
- Of that, **5.0 seconds was a single LLM call** — the model itself, not your code.
- The retriever was fast (**180ms**); the LLM API was slow.
- If you wanted to make this request faster, no amount of optimizing your retriever would help; the bottleneck is the model provider.

## Inspecting an LLM Span

Click any span labeled with the LLM operation (e.g. `ChatLiteLLM`, `ChatOpenAI`, the model class name). The right-hand panel shows the span's **attributes**. Key ones to look for:

| Attribute | Meaning | Visible by default? |
|---|---|---|
| `openinference.span.kind` | Span category — `LLM`, `CHAIN`, `RETRIEVER`, `TOOL`, `EMBEDDING`, etc. | Yes |
| `llm.model_name` | The exact model used (e.g. `gpt-5`, `claude-3-opus-20240229`) | Yes |
| `llm.provider` | Provider name (e.g. `openai`, `anthropic`) | Yes |
| `llm.token_count.prompt` | Tokens in the input | Yes |
| `llm.token_count.completion` | Tokens in the output | Yes |
| `llm.token_count.total` | Sum of the above | Yes |
| `llm.invocation_parameters` | Temperature, max_tokens, and other call options | Yes |
| `input.value` | The full prompt sent to the model (system + user messages, JSON-encoded) | **No** — hidden by default |
| `output.value` | The model's response | **No** — hidden by default |
| `llm.input_messages.*` / `llm.output_messages.*` | Per-message content | **No** — hidden by default |
| `llm.prompt_template.variables` / `.template` | Variables substituted into a prompt template | **No** — hidden by default |
| `retrieval.documents.*.document.content` / `.metadata` | RAG retrieved document content | **No** — hidden by default |
| `tool.parameters` | Tool call inputs | **No** — hidden by default |

For non-LLM spans (chains, tools, retrievers), the relevant attributes vary; the consistent one is `openinference.span.kind`, which tells you what kind of work the span represents.

### Why prompts and responses are hidden by default

User chat text, retrieved RAG context, and model responses can contain deployment-specific or private content. By default, the {{% short_app_ref %}} server configures OpenInference to omit these payloads from exported spans unless payload export is enabled.

Additional message-related attributes, including prompt template variables, retrieved document content, and tool parameters, follow the same default visibility setting as the main `input.value` / `output.value` payloads.

The cost categories of telemetry — *what model was called, how long it took, how many tokens, what parameters* — remain fully visible and are sufficient for monitoring, latency triage, and cost rollups.

### Opting into full payloads

For prompt-engineering work, agent debugging, or development against an isolated backend, full payloads can be enabled at the server level by setting the standard OpenInference env vars to `false`:

```bash
# in .env.dev (or shell), when the configured backend is approved for
# prompt and response payloads
OPENINFERENCE_HIDE_INPUTS=false
OPENINFERENCE_HIDE_OUTPUTS=false
OPENINFERENCE_HIDE_INPUT_MESSAGES=false
OPENINFERENCE_HIDE_OUTPUT_MESSAGES=false
OPENINFERENCE_HIDE_INPUT_TEXT=false
OPENINFERENCE_HIDE_OUTPUT_TEXT=false
```

Set only the variants you need; e.g., `OPENINFERENCE_HIDE_OUTPUTS=false` makes response attributes visible while keeping prompts hidden. Choose these settings per deployment before changing the default.

## Reading Logs in the Context of a Trace

Application logs flow alongside traces. Every log record emitted while a span is active carries that span's `trace_id` and `span_id`, which means the backend can show the logs that ran during a specific span without grep'ing files.

In SigNoz, two paths to the same data:

1. **From a trace** — open a trace, click any span, and choose the **Go to Logs** action (or the equivalent button on the span panel). The logs view opens pre-filtered to that span's `trace_id`, optionally narrowed to its `span_id` and time window.
2. **From the logs view directly** — open **Logs** from the left navigation. Filter by `service.name = ai-optimizer-server`, then by `trace_id` if you want to inspect a specific request.

Useful filter combinations (save them — see [Saved Views](#saved-views)):

| Filter | Purpose |
|---|---|
| `severity_text = ERROR` and `service.name = ai-optimizer-server` | All recent errors across the server |
| `trace_id = <id from a slow trace>` | Everything the app logged while a particular request ran |
| `body contains "<exception or pattern>"` | Free-text search across logs |

Because logs are correlated *automatically*, you do not need to add `trace_id` to your log format strings — the backend joins records to traces by attribute. The existing console log format remains unchanged on stdout.

## Service-Level Monitoring

Aggregate health lives in **Services → `ai-optimizer-server`**. The headline numbers populate automatically from the FastAPI request spans:

| Metric | Meaning |
|---|---|
| Request rate (RPS) | Requests per second to the server |
| Error rate (%) | Share of requests that returned a 5xx (or non-2xx) status |
| p50 / p95 / p99 latency | Response-time distribution — p99 is the slow tail |

These metrics are sliced per route (`/v1/chat/completions`, `/v1/healthz`, etc.), so you can see whether one endpoint is dragging down overall numbers.

Set an alert rule on any of these (SigNoz **Alerts → New Alert**) for production paging. Common starting points:

- `p99 latency > 10s for 5 minutes`
- `error rate > 1% for 5 minutes`
- `request rate drops to 0 for 2 minutes` (canary for a dead service)

## Common Investigation Workflows

### "This request was slow — why?"

1. **Traces → service: `ai-optimizer-server`**, filter by route and time window.
2. Sort by duration descending. Open the slow trace.
3. Read the flame graph: the widest child bar of the root is the bottleneck.
4. If it's an LLM span, check `llm.model_name` and `llm.invocation_parameters` — was a slow model used? Were max_tokens unusually high?
5. If it's a retriever or HTTP call, check the corresponding `CLIENT` span's status, target host, and duration distribution across other traces.

### "This answer was wrong — what did the agent see?"

By default, prompts and responses are not exported (see [Why prompts and responses are hidden by default](#why-prompts-and-responses-are-hidden-by-default)). The trace still reveals which spans ran, with what model, in what order, and how long each took — useful structural debugging — but not the literal content.

For prompt-engineering work, enable payload export on a development backend:

1. Set `OPENINFERENCE_HIDE_INPUTS=false` and `OPENINFERENCE_HIDE_OUTPUTS=false` in `.env.dev` (and the related `_MESSAGES` / `_TEXT` variants if you need per-message detail).
2. Restart the server and re-run the failing request.
3. In the trace, open each `LLM`-kind span in order and read `input.value` and `output.value` — these are now exactly what was sent and received.
4. Inspect `RETRIEVER`-kind spans for the context that was supplied to the LLM.

Return these settings to their defaults before using a shared environment.

### "Something logged a warning during this request — what was happening?"

1. Find the slow or failed trace.
2. From any span (or the trace root), use **Go to Logs** to switch to the logs view filtered to this `trace_id`.
3. Read the log timeline. Each line is timestamped within the span's window, so you can see what the application was *thinking* at each moment alongside what it was *doing* (the spans).

This pairs well with the previous workflow: spans tell you *what ran*; logs tell you *what the code wanted to say while it was running*.

### "How much did the last hour of chat cost?"

1. SigNoz **Traces** → filter by service and time window (`now-1h..now`).
2. Build a query that sums `llm.token_count.prompt` and `llm.token_count.completion` grouped by `llm.model_name`.
3. In a dashboard or spreadsheet, multiply each model's tokens by its provider's per-1k-token rate.

SigNoz captures the tokens; the cost calculation is yours because pricing is provider- and time-specific. Once you build the dashboard once, it keeps working.

## Saved Views

SigNoz lets you save filter combinations on the Traces and Logs explorers. Build a small library and bookmark them as your runbook:

| Saved View | Filter | When to use |
|---|---|---|
| **Slow chat requests** | service=`ai-optimizer-server`, route=`/v1/chat/completions`, duration > p95 | Daily check on tail latency |
| **5xx errors** | service=`ai-optimizer-server`, http.status_code >= 500 | First click when paged |
| **Failed LLM calls** | `openinference.span.kind`=`LLM`, status=ERROR | Provider outages, rate limits, bad credentials |
| **Expensive prompts** | `openinference.span.kind`=`LLM`, `llm.token_count.prompt` > 4000 | Catch runaway prompt growth |
| **Recent error logs** | `severity_text` = `ERROR`, service=`ai-optimizer-server`, last 1h | Quick look at what's misbehaving right now |

Each saved view takes about 30 seconds to set up. The investment pays off the first time you don't have to remember filter syntax at 2 a.m.

## What These Traces Do Not Show

- **Cost dashboards** are not pre-built. Tokens are captured; price-per-token formulas are configured by you in SigNoz dashboards.
- **Prompt/response diffing** for prompt engineering is not a SigNoz feature. With the `OPENINFERENCE_HIDE_*` opt-in (see [Opting into full payloads](#opting-into-full-payloads)), prompts are present in `input.value`, but comparing two prompts side-by-side is better done in a dedicated LLM eval tool (LangSmith, Phoenix) when needed.
- **FastMCP server-side dispatch** is not yet wrapped in dedicated spans. Tool calls appear via LangChain spans (showing the agent's intent) and via outbound `httpx` spans, but the MCP server's handler logic is not separately traced.
- **Streamlit client-side activity** is not instrumented; the client is treated as a thin REST caller and its work appears in the server-side traces it triggers.

## The Habit Worth Forming

When something in the app looks wrong — slow, broken, returning unexpected output — open SigNoz **before** opening logs or code. Find the trace, read the spans, then act. Logs tell you what the application *thought* was happening; traces tell you what *actually* happened, with exact durations, model names, and tokens (and, when payload export is opted in, the literal prompts and responses).

Most observability investments pay off slowly. Reading traces pays off the first time you do it.
