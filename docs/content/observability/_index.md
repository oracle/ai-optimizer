+++
title = 'Observability'
weight = 38
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore quickstarts streamlit fzmp httpx instrumentor langchain litellm parentbased relref signoz traceidratio uvicorn
-->

The {{% short_app_ref %}} **Server** can emit [OpenTelemetry](https://opentelemetry.io) traces and logs to any OTLP-compatible backend (e.g. [SigNoz](https://signoz.io), [Jaeger](https://www.jaegertracing.io), [Grafana Tempo](https://grafana.com/oss/tempo)). Telemetry is **opt-in** — disabled by default and activated entirely via environment variables.

## What Is Instrumented

Telemetry covers HTTP traffic, LangChain/LangGraph orchestration, LLM invocations, and application logs on the server:

| Source | Signal | What's Captured |
|---|---|---|
| FastAPI | Trace | One `SERVER` span per inbound HTTP request, with route, method, status code, peer info |
| LangChain / LangGraph | Trace | One span per chain, agent, tool, retriever, or graph node invocation. LLM calls (including those routed via `langchain-litellm`) carry semantic attributes — model name, prompt, response, prompt/completion token counts |
| `httpx` | Trace | One `CLIENT` span per outbound call (LLM provider APIs, MCP, etc.) |
| `requests` | Trace | One `CLIENT` span per outbound call (used by the OCI SDK) |
| Python `logging` | Log | All log records emitted by application code, uvicorn, and dependencies, automatically correlated to the active trace and span |

A typical chat request produces a tree like:

```
POST /v1/chat                            SERVER
└── LangGraph invocation                 INTERNAL
    ├── retrieve node                    INTERNAL
    └── generate node                    INTERNAL
        └── ChatLiteLLM.invoke           INTERNAL  ← model, tokens, prompt/response
            └── HTTP POST <provider>     CLIENT    ← transport timing
```

The LangChain LLM span carries semantic LLM information (model, tokens, content); the child `httpx` span carries transport-level information (URL, status, duration). They are complementary, not duplicates.

Log records emitted during the lifetime of any span carry that span's `trace_id` and `span_id`, so a backend can show the logs from a specific span when its trace is opened.

The Streamlit **Client** is not instrumented; it is a thin REST client whose work is reflected in the server-side traces it triggers.

## Enabling

### 1. Install the `otel` extra

The OpenTelemetry packages live in an optional dependency group. They are not installed by default.

```bash
pip install -e ".[server,otel]"
```

For container builds, include `otel` in the extras passed to your install step.

### 2. Configure the exporter

Two paths, chosen with `OTEL_TRACES_EXPORTER`:

#### Backend export (production)

Point the server at any OTLP receiver:

```bash
# In .env.dev (or .env.prd, etc.)
OTEL_EXPORTER_OTLP_ENDPOINT=http://signoz-otel-collector:4317
```

The default protocol is gRPC (port `4317`). For HTTP/protobuf (port `4318`):

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://signoz-otel-collector:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
```

#### Console export (debugging, no backend required)

Dumps each span as JSON to stdout. Useful for verifying instrumentation locally without standing up a backend.

```bash
OTEL_TRACES_EXPORTER=console
```

{{% notice style="code" title="Console exporter cost" icon="triangle-exclamation" %}}
The console exporter flushes synchronously per span and can produce significant log volume. Use it for local debugging only; do not enable it in production.
{{% /notice %}}

### 3. Start the server and verify

```bash
./src/entrypoint.py server
curl http://localhost:8000/v1/healthz
```

In **console mode**, span JSON is printed to stdout immediately. In **backend mode**, the server logs `OTel telemetry initialized: service=ai-optimizer-server exporters=['otlp']` at startup; traces and logs then appear in the backend UI within a few seconds.

If you do not see this log line, telemetry did not initialize — check the [Troubleshooting](#troubleshooting) section below.

{{% notice style="code" title="Console mode and logs" icon="circle-info" %}}
Log export to OTLP only activates when the OTLP trace exporter is active. With `OTEL_TRACES_EXPORTER=console` (debug mode), application logs continue to stream to stdout via the existing logging configuration; they are not duplicated to OTLP.
{{% /notice %}}

{{% notice style="code" title="Log export is opt-in" icon="triangle-exclamation" %}}
Application log export to OTLP is **disabled by default**, even when tracing is configured. Enable it with [`AIO_OTEL_LOGS_ENABLED=true`]({{% relref "/configuration#observability" %}}) only for backends intended to retain application logs.

Span attribute visibility is controlled separately through the OpenInference settings below.
{{% /notice %}}

## Environment Variables

The {{% short_app_ref %}} honors the standard [OpenTelemetry SDK environment variables](https://opentelemetry.io/docs/languages/sdk-configuration/). The most relevant ones for operators:

### Endpoint and protocol

| Variable | Description | Default |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP receiver URL (all signals) | _(unset = OTLP disabled)_ |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | Trace-specific endpoint (overrides the generic one) | _(unset)_ |
| `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` | Log-specific endpoint (overrides the generic one) | _(unset)_ |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` or `http/protobuf` (all signals) | `grpc` |
| `OTEL_EXPORTER_OTLP_TRACES_PROTOCOL` | Trace-specific protocol (overrides the generic one) | _(unset)_ |
| `OTEL_EXPORTER_OTLP_LOGS_PROTOCOL` | Log-specific protocol (overrides the generic one) | _(unset)_ |
| `OTEL_EXPORTER_OTLP_INSECURE` | If `true`, skips TLS for gRPC OTLP. Required for plaintext local SigNoz. | `false` |
| `OTEL_EXPORTER_OTLP_HEADERS` | Comma-separated `k=v` headers (e.g. for vendor auth tokens) | _(unset)_ |

### Exporter selection

| Variable | Description | Default |
|---|---|---|
| `OTEL_TRACES_EXPORTER` | Comma-separated list. Supported values: `otlp`, `console`, `none`. Unsupported values are ignored. | `otlp` |
| `OTEL_LOGS_EXPORTER` | Set to `none` to disable log export when `AIO_OTEL_LOGS_ENABLED=true` is in effect. | `otlp` |

### Resource attributes

| Variable | Description | Default |
|---|---|---|
| `OTEL_SERVICE_NAME` | Service name shown in the backend | `ai-optimizer-server` |
| `OTEL_RESOURCE_ATTRIBUTES` | Comma-separated `k=v` attributes attached to every span (e.g. `deployment.environment=prd,service.namespace=ai`) | _(unset)_ |

### Sampling

| Variable | Description | Default |
|---|---|---|
| `OTEL_TRACES_SAMPLER` | Sampler. Common: `parentbased_always_on` (default), `parentbased_traceidratio` (probabilistic) | `parentbased_always_on` |
| `OTEL_TRACES_SAMPLER_ARG` | Sampler argument (for ratio sampler: `0.0`–`1.0`, e.g. `0.1` for 10%) | _(none)_ |

### Batch span processor tuning

The `OTEL_BSP_*` family (`OTEL_BSP_MAX_QUEUE_SIZE`, `OTEL_BSP_SCHEDULE_DELAY`, etc.) is honored by the SDK without code changes; tune in production if you observe span drops or back-pressure. See the [SDK configuration spec](https://opentelemetry.io/docs/languages/sdk-configuration/general/) for the full list.

## Resource Attributes Set by the Application

The server sets the following attributes by default. All can be overridden via `OTEL_RESOURCE_ATTRIBUTES` or the dedicated env var.

| Attribute | Source | Example |
|---|---|---|
| `service.name` | `OTEL_SERVICE_NAME` env, else built-in default | `ai-optimizer-server` |
| `service.version` | Application version (from package metadata) | `2.2.1` |
| `deployment.environment` | `AIO_ENV` env (default `dev`) | `prd` |
| `service.instance.id` | `HOSTNAME` env, else a per-process UUID | `ai-optimizer-server-7c5b9-fzmp2` |

Operator-supplied values via `OTEL_RESOURCE_ATTRIBUTES` always take precedence over these defaults.

## Deployment Patterns

### Bare-metal / VM

Set the variables in `.env.dev` (or whichever `.env.{AIO_ENV}` file is loaded), or export them in the shell before running the entrypoint:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
./src/entrypoint.py server
```

### Container (Docker / Podman)

Pass the variables at run time:

```bash
docker run --rm \
  -e OTEL_EXPORTER_OTLP_ENDPOINT=http://signoz-otel-collector:4317 \
  -e OTEL_RESOURCE_ATTRIBUTES=deployment.environment=staging \
  ai-optimizer:latest server
```

Or via an env-file (`--env-file`).

If running SigNoz on the same Docker host (e.g. via the SigNoz docker-compose), point at the SigNoz collector container by service name on the shared network.

### Kubernetes / Helm

The bundled Helm chart exposes OpenTelemetry settings under `server.otel`. Two paths:

**1. Bring your own OTLP collector** — point `endpoint` at a separately-deployed SigNoz, Jaeger, Tempo, or vendor agent:

```yaml
# values overlay
server:
  otel:
    enabled: true
    endpoint: http://signoz-otel-collector.observability.svc.cluster.local:4317
    insecure: true   # plaintext gRPC inside the cluster
    resourceAttributes:
      service.namespace: ai-optimizer
    # logsEnabled: true   # opt-in; review backend retention first
```

**2. Install SigNoz alongside the application** — flip `signoz.enabled=true` and the chart deploys SigNoz as a subchart. The server's OTLP endpoint is then auto-defaulted to the in-cluster collector service URL; you only configure the OTel-side switches:

```yaml
signoz:
  enabled: true
server:
  otel:
    enabled: true
    insecure: true   # the in-chart collector serves plaintext gRPC
```

The published image already includes the `[otel]` extra, so `enabled: true` works against the default image. Within Kubernetes, `service.instance.id` is auto-populated from `HOSTNAME` (the pod name), giving stable per-pod identity in the backend. `deployment.environment` is set automatically from the chart's `global.env` value.

If `enabled: true` is set without an endpoint (and without `tracesExporter: console` for local debugging or `signoz.enabled=true` to use the in-chart collector), `helm template` / `helm install` fails fast rather than silently producing zero telemetry.

## Troubleshooting

| Symptom | Likely Cause | Remedy |
|---|---|---|
| No `OTel telemetry initialized` log line at startup | The `[otel]` extra is not installed, OR no exporter is configured | Re-run `pip install -e ".[server,otel]"`; set `OTEL_EXPORTER_OTLP_ENDPOINT` or `OTEL_TRACES_EXPORTER=console` |
| Log line appears, but no traces in backend | gRPC TLS handshake failing against a plaintext collector | Set `OTEL_EXPORTER_OTLP_INSECURE=true`, or switch to `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf` with a `http://` URL |
| `OTLP grpc exporter requested but not installed` warning | The `opentelemetry-exporter-otlp` package is missing or partially installed | Reinstall with the `[otel]` extra |
| Operator-set `OTEL_RESOURCE_ATTRIBUTES` value not visible on spans | Confused with a comma-delimited list — use commas, not spaces or semicolons | `OTEL_RESOURCE_ATTRIBUTES=k1=v1,k2=v2` |
| `OTEL_TRACES_EXPORTER` set to a value other than `otlp`, `console`, or `none` | Unsupported values are silently dropped | Use a supported value or set both: `OTEL_TRACES_EXPORTER=otlp,console` |
| Per-request overhead but no spans recorded | OTLP exporter package missing while `OTEL_TRACES_EXPORTER=otlp`; the SDK now bails before installing instrumentation in this case | Reinstall with `[otel]`; check startup logs for the `not installed; skipping` warning |

## Backend-Specific Quickstarts

For step-by-step instructions on standing up a specific OTLP backend and pointing the server at it, see:

- [SigNoz Quickstart]({{% relref "/observability/signoz" %}})
