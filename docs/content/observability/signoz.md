+++
title = 'SigNoz Quickstart'
weight = 10
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore signoz otlp clickhouse
-->

This page walks through standing up a self-hosted [SigNoz](https://signoz.io) instance on a single host and pointing the {{< short_app_ref >}} **Server** at it. Once complete, server requests appear as traces in the SigNoz UI within seconds of being issued.

The same data path works against any other OTLP backend (Jaeger, Grafana Tempo, vendor-managed receivers) — only the install steps and endpoint URL differ.

## Prerequisites

- [Podman](https://podman.io) with the `compose` plugin on the host that will run SigNoz. Docker is also supported — substitute `docker` for `podman` in the commands below.
- The {{< short_app_ref >}} server installed with the `[otel]` extra (see [Observability]({{% relref "/observability" %}}) for the install command).
- Outbound network reachability from the server process to the SigNoz host on the OTLP ports (`4317` for gRPC, `4318` for HTTP).

## 1. Stand Up SigNoz

SigNoz publishes a Compose stack containing ClickHouse, the OTel Collector, the query service, and the frontend. Follow the official install instructions at <https://signoz.io/docs/install/docker/> (the same compose file works with `podman compose`), which generally amount to:

```bash
git clone https://github.com/SigNoz/signoz tmp/signoz
cd tmp/signoz/deploy/docker
podman compose up -d
```

{{% notice style="code" title="Verify the path" icon="circle-info" %}}
The exact directory and entrypoint inside the SigNoz repository changes between releases. Always check the SigNoz documentation linked above for the current command before running it.
{{% /notice %}}

The first run pulls several gigabytes of images and takes a few minutes. When the stack is healthy:

| Endpoint | URL | Purpose |
|---|---|---|
| Frontend (UI) | `http://<host>:8080` | Web console |
| OTLP gRPC | `<host>:4317` | Default span receiver |
| OTLP HTTP | `<host>:4318` | Alternate receiver |

Open <http://localhost:8080> in your browser to reach the SigNoz UI. The first visit prompts you to create an admin account; complete this before continuing.

## 2. Configure the Server

Set the following variables in your `.env.{AIO_ENV}` file (or export them in the shell before launching the entrypoint):

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_EXPORTER_OTLP_INSECURE=true
```

Replace `localhost` with the SigNoz host's reachable address if the server runs elsewhere — see [Networking](#networking) below.

If `OTEL_TRACES_EXPORTER=console` was previously set for local debugging, remove or comment it out so the OTLP exporter takes effect.

{{% notice style="code" title="Why OTEL_EXPORTER_OTLP_INSECURE=true is required" icon="triangle-exclamation" %}}
The default SigNoz Compose stack does not terminate TLS on the OTLP ports. Without this variable, the gRPC OTLP exporter attempts a TLS handshake, fails silently, and no spans are delivered. Once you put SigNoz behind a TLS-terminating proxy or load balancer, remove this variable.
{{% /notice %}}

## 3. Verify End-to-End

Restart the server and confirm initialization succeeded:

```bash
./src/entrypoint.py server
```

Look for the startup log line:

```
OTel tracing initialized: service=ai-optimizer-server exporters=['otlp']
```

If the line is absent or `exporters=[]`, see [Troubleshooting]({{% relref "/observability/#troubleshooting" %}}) on the main Observability page.

Generate a request:

```bash
curl http://localhost:8000/v1/healthz
```

Return to the SigNoz UI at <http://localhost:8080>. Use the left-hand navigation:

1. **Services** view — `ai-optimizer-server` appears within ~30 seconds (the collector batches before flushing). Request rate, p99 latency, and error rate populate from incoming traffic.
2. **Traces** view — filter by service `ai-optimizer-server` and open any trace. The flame graph shows the FastAPI `SERVER` span as the root, with two short ASGI `http send` child spans (`http.response.start` and `http.response.body`).

When outbound calls are made (LLM provider APIs, OCI SDK requests, etc.), additional `CLIENT` spans appear nested under the parent SERVER span automatically.

## Networking

The endpoint URL depends on where the {{< short_app_ref >}} server runs relative to the SigNoz host.

| Server location | SigNoz location | `OTEL_EXPORTER_OTLP_ENDPOINT` |
|---|---|---|
| Bare-metal, same host as SigNoz | Local `podman compose` | `http://localhost:4317` |
| Podman container on macOS or Windows | Local `podman compose` | `http://host.containers.internal:4317` |
| Podman container on Linux | Local `podman compose` | Put both on the same compose network and use the SigNoz collector's service name (e.g. `http://otel-collector:4317`); otherwise use the Podman bridge gateway IP |
| Different host or VM | Remote SigNoz | `http://<signoz-host>:4317` (open the firewall on `4317` / `4318`) |
| Kubernetes cluster | SigNoz running in-cluster | The cluster-internal DNS, e.g. `http://signoz-otel-collector.monitoring:4317` |

When the server is itself running in a container, set the variable at container launch (e.g. `podman run -e OTEL_EXPORTER_OTLP_ENDPOINT=...`) rather than in `.env.{AIO_ENV}` — environment variables on the host do not propagate into a child container.

{{% notice style="code" title="Docker Desktop users" icon="circle-info" %}}
On Docker (instead of Podman), substitute `host.docker.internal` for `host.containers.internal` on macOS/Windows, and use the Docker bridge gateway IP on Linux.
{{% /notice %}}

## Stopping and Cleaning Up

To stop SigNoz without losing data, run `podman compose down` from the SigNoz deploy directory (`tmp/signoz/deploy/docker`). To wipe all collected traces and start fresh, follow the volume-removal instructions in SigNoz's documentation — the collected data lives in the ClickHouse volume, not the application image.
