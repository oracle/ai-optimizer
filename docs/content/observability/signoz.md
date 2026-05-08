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

{{% notice style="code" title="Running on Kubernetes?" icon="circle-info" %}}
The bundled Helm chart can deploy SigNoz alongside the application as a subchart. Set both `signoz.enabled=true` (deploys the collector + UI) and `server.otel.enabled=true` (turns on the application-side exporter); the OTLP endpoint is then wired automatically. See [SigNoz subchart]({{% relref "/advanced/helm#signoz-subchart" %}}). The Compose-based steps below are for bare-metal / single-host setups.
{{% /notice %}}

## Prerequisites

- [Podman](https://podman.io) with the `compose` plugin on the host that will run SigNoz. Docker is also supported — substitute `docker` for `podman` in the commands below.
- The {{< short_app_ref >}} server installed with the `[otel]` extra (see [Observability]({{% relref "/observability" %}}) for the install command).
- Outbound network reachability from the server process to the SigNoz host on the OTLP ports (`4317` for gRPC, `4318` for HTTP).

## 1. Stand Up SigNoz

SigNoz publishes a Compose stack containing ClickHouse, the OTel Collector, the query service, and the frontend. Follow the official install instructions at <https://signoz.io/docs/install/docker/> (the same compose file works with `podman compose`), which generally amount to:

```bash
git clone https://github.com/SigNoz/signoz tmp/signoz
cd tmp/signoz/deploy/docker
podman compose -p ai-optimizer-signoz up -d
```

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

To also ship application logs to SigNoz (correlated to traces by `trace_id`/`span_id`), explicitly enable log export:

```bash
AIO_OTEL_LOGS_ENABLED=true
```

Log export is opt-in. See [Log export is opt-in]({{% relref "/observability/#log-export-is-opt-in" %}}) on the main Observability page before enabling it for a shared or vendor-managed backend.

## 3. Verify End-to-End

Restart the server and confirm initialization succeeded:

```bash
./src/entrypoint.py server
```

Look for the startup log line:

```
OTel telemetry initialized: service=ai-optimizer-server exporters=['otlp']
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

## 4. Load the Starter Dashboards and Alerts

The repository ships a curated set of SigNoz assets under [`observe/signoz/`](https://github.com/oracle/ai-optimizer/tree/main/observe/signoz) so a fresh install does not start from a blank UI:

- One overview dashboard — request rate, p95 latency, 5xx rate, LLM call rate, LLM tokens by model.
- Three starter alert rules — 5xx spike, chat-completions p95 breach, telemetry silence (no traces received).

The fastest path is the bundled bootstrap script, which loads both dashboards and alerts via SigNoz's HTTP API. Pass the admin credentials you set on first UI visit; the script prompts for your password and logs in for you:

```bash
observe/signoz/bootstrap-signoz.py \
  --host http://localhost:8080     \
  --email <admin-email>
```

For CI / SSO setups, pass a pre-fetched JWT as `--token` (or `$SIGNOZ_TOKEN`) instead — it bypasses the login step. Manual paths exist as well — dashboards can be imported via **Dashboards → New dashboard → Import JSON**, but the SigNoz UI has no JSON import for alerts, so the script (or the UI form) is the only way to load them. See the directory's [README](https://github.com/oracle/ai-optimizer/blob/main/observe/signoz/README.md) for the full workflow, including the prerequisite that at least one chat completion has been ingested before bootstrapping (LLM-related dashboard panels filter on attribute keys that SigNoz only indexes once it has seen them in real spans).

The committed JSON is the source of truth: SigNoz's own state lives in container volumes and is wiped on a re-install, so changes made in the UI need to be exported back to this directory to survive.

## Networking

The endpoint URL depends on where the {{< short_app_ref >}} server runs relative to the SigNoz host.

| Server location | SigNoz location | `OTEL_EXPORTER_OTLP_ENDPOINT` |
|---|---|---|
| Bare-metal, same host as SigNoz | Local `podman compose` | `http://localhost:4317` |
| Podman container on macOS or Windows | Local `podman compose` | `http://host.containers.internal:4317` |
| Podman container on Linux | Local `podman compose` | Put both on the same compose network and use the SigNoz collector's service name (e.g. `http://otel-collector:4317`); otherwise use the Podman bridge gateway IP |
| Different host or VM | Remote SigNoz | `http://<signoz-host>:4317` (open the firewall on `4317` / `4318`) |
| Kubernetes cluster | SigNoz running in-cluster | The cluster-internal DNS, e.g. `http://signoz-otel-collector.monitoring:4317`. Set via the chart's [`server.otel.*` values]({{% relref "/advanced/helm#server-opentelemetry-configuration" %}}), not the raw env var. |

When the server is itself running in a container, set the variable at container launch (e.g. `podman run -e OTEL_EXPORTER_OTLP_ENDPOINT=...`) rather than in `.env.{AIO_ENV}` — environment variables on the host do not propagate into a child container.

{{% notice style="code" title="Docker Desktop users" icon="circle-info" %}}
On Docker (instead of Podman), substitute `host.docker.internal` for `host.containers.internal` on macOS/Windows, and use the Docker bridge gateway IP on Linux.
{{% /notice %}}

## Stopping and Cleaning Up

Run both commands from the SigNoz deploy directory (`tmp/signoz/deploy/docker`).

To stop SigNoz **without losing data**:

```bash
podman compose -p ai-optimizer-signoz down
```

The containers are removed; the named volumes (ClickHouse, SigNoz metadata, etc.) remain. A subsequent `compose up` rejoins the same volumes and all collected traces / logs / dashboards are still there.

To **wipe everything** and start fresh — collected traces, dashboards built in the UI, alert configurations, the lot:

```bash
podman compose -p ai-optimizer-signoz down -v
```

The `-v` flag deletes the named volumes Compose declared. After this, anything you built in the SigNoz UI is gone; the assets in [`observe/signoz/`](https://github.com/oracle/ai-optimizer/tree/main/observe/signoz) are the only way to bring dashboards and alerts back automatically.

The project name (`ai-optimizer-signoz`) must match the one used at `compose up`. If you started SigNoz without `-p`, substitute the directory-derived default (`docker` if you ran from `tmp/signoz/deploy/docker`).
