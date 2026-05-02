+++
title = 'Observability'
weight = 50
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore signoz jaeger tempo otlp parentbased traceidratio
-->

The {{< short_app_ref >}} **Server** can emit [OpenTelemetry](https://opentelemetry.io) traces to any OTLP-compatible backend (e.g. [SigNoz](https://signoz.io), [Jaeger](https://www.jaegertracing.io), [Grafana Tempo](https://grafana.com/oss/tempo)). Tracing is **opt-in** — disabled by default and activated entirely via environment variables.

## What Is Instrumented

Tracing covers HTTP-level activity on the server:

| Source | Spans Emitted |
|---|---|
| FastAPI | One `SERVER` span per inbound HTTP request, with route, method, status code, peer info |
| `httpx` | One `CLIENT` span per outbound call (LLM provider APIs, MCP, etc.) |
| `requests` | One `CLIENT` span per outbound call (used by the OCI SDK) |

The Streamlit **Client** is not instrumented; it is a thin REST client whose work is reflected in the server-side traces it triggers.

{{% notice style="code" title="Not yet covered" icon="circle-info" %}}
Internal LangGraph node execution, LLM token counts / costs, and FastMCP tool invocations are not yet instrumented. Only the HTTP boundaries above are traced today.
{{% /notice %}}

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

In **console mode**, span JSON is printed to stdout immediately. In **backend mode**, the server logs `OTel tracing initialized: service=ai-optimizer-server exporters=['otlp']` at startup, and traces appear in the backend UI within a few seconds.

If you do not see this log line, tracing did not initialize — check the [Troubleshooting](#troubleshooting) section below.

## Environment Variable Reference

The {{< short_app_ref >}} honors the standard [OpenTelemetry SDK environment variables](https://opentelemetry.io/docs/languages/sdk-configuration/). The most relevant ones for operators:

### Endpoint and protocol

| Variable | Description | Default |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP receiver URL (all signals) | _(unset = OTLP disabled)_ |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | Trace-specific endpoint (overrides the generic one) | _(unset)_ |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` or `http/protobuf` (all signals) | `grpc` |
| `OTEL_EXPORTER_OTLP_TRACES_PROTOCOL` | Trace-specific protocol (overrides the generic one) | _(unset)_ |
| `OTEL_EXPORTER_OTLP_INSECURE` | If `true`, skips TLS for gRPC OTLP. Required for plaintext local SigNoz. | `false` |
| `OTEL_EXPORTER_OTLP_HEADERS` | Comma-separated `k=v` headers (e.g. for vendor auth tokens) | _(unset)_ |

### Exporter selection

| Variable | Description | Default |
|---|---|---|
| `OTEL_TRACES_EXPORTER` | Comma-separated list. Supported values: `otlp`, `console`, `none`. Unsupported values are ignored. | `otlp` |

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

The bundled Helm chart does not yet expose OpenTelemetry settings as first-class values. Until first-class support lands, set the variables via the chart's existing env-injection mechanism (e.g. `envSecret` or the chart's pod env list), pointing at a SigNoz / OTel Collector service running in-cluster:

```yaml
# values overlay
server:
  env:
    OTEL_EXPORTER_OTLP_ENDPOINT: http://signoz-otel-collector.monitoring:4317
    OTEL_RESOURCE_ATTRIBUTES: "deployment.environment=prd,service.namespace=ai-optimizer"
```

Within Kubernetes, `service.instance.id` is auto-populated from `HOSTNAME` (the pod name), giving stable per-pod identity in the backend.

## Troubleshooting

| Symptom | Likely Cause | Remedy |
|---|---|---|
| No `OTel tracing initialized` log line at startup | The `[otel]` extra is not installed, OR no exporter is configured | Re-run `pip install -e ".[server,otel]"`; set `OTEL_EXPORTER_OTLP_ENDPOINT` or `OTEL_TRACES_EXPORTER=console` |
| Log line appears, but no traces in backend | gRPC TLS handshake failing against a plaintext collector | Set `OTEL_EXPORTER_OTLP_INSECURE=true`, or switch to `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf` with a `http://` URL |
| `OTLP grpc exporter requested but not installed` warning | The `opentelemetry-exporter-otlp` package is missing or partially installed | Reinstall with the `[otel]` extra |
| Operator-set `OTEL_RESOURCE_ATTRIBUTES` value not visible on spans | Confused with a comma-delimited list — use commas, not spaces or semicolons | `OTEL_RESOURCE_ATTRIBUTES=k1=v1,k2=v2` |
| `OTEL_TRACES_EXPORTER` set to a value other than `otlp`, `console`, or `none` | Unsupported values are silently dropped | Use a supported value or set both: `OTEL_TRACES_EXPORTER=otlp,console` |
| Per-request overhead but no spans recorded | OTLP exporter package missing while `OTEL_TRACES_EXPORTER=otlp`; the SDK now bails before installing instrumentation in this case | Reinstall with `[otel]`; check startup logs for the `not installed; skipping` warning |

## Verifying End-to-End with SigNoz

The vendor walkthrough at <https://signoz.io/docs/langchain-observability/> remains a useful reference for standing up self-hosted SigNoz and confirming the data path. Once SigNoz is running and reachable:

1. Set `OTEL_EXPORTER_OTLP_ENDPOINT` to the SigNoz OTel Collector URL.
2. Restart the server.
3. Issue any request (e.g. `GET /v1/healthz`).
4. In SigNoz, the `ai-optimizer-server` service should appear in the Services list within a minute, and the request should be visible as a trace in the Traces view.
