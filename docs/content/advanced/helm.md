+++
title = 'Helm Chart'
weight = 5
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore genai ollama sidb ashburn autonomousdatabase myadb mydbhost ocid relref signoz subchart
-->

The {{% full_app_ref %}} was specifically designed to run on infrastructure supporting microservices architecture, including [Kubernetes](https://kubernetes.io/).  A [Helm](https://helm.sh/) Chart is provided to make the deployment easier.

This page is a deployment overview plus the handful of choices that matter in practice. For the full configuration surface, read [`helm/values.yaml`](https://github.com/oracle/ai-optimizer/blob/main/helm/values.yaml) or run:

```bash
helm show values ai-optimizer/ai-optimizer
```

{{% notice style="code" title="Go Local" icon="laptop" %}}
Want to try it on your laptop first? A full walkthrough on a local Kubernetes cluster using Docker container "nodes" via the [Kind](https://kind.sigs.k8s.io/) tool is [provided below](#kind-example).
{{% /notice %}}


## Before You Install

You'll need:

1. A Kubernetes cluster.
1. A namespace for the release.
1. Pinned container images for the server and client.
1. An API key Secret or `global.api.apiKey`.
1. A stable Client cookie signing Secret or `client.cookieSecret`.
1. Database connectivity, unless you only want the application pods rendered without database wiring.

If you're installing from a local checkout, fetch the subchart dependencies first:

```bash
cd helm
helm repo add --force-update signoz https://charts.signoz.io
helm dependency build
```

## Images

{{% notice style="code" title="No Floating Tags" icon="lock" %}}
The chart rejects `latest`, `head`, and `canary` at render time. Build immutable tags (typically the application version you're deploying) and pass them through `server.image.tag` and `client.image.tag`. Leave both empty to inherit `Chart.appVersion`.
{{% /notice %}}

Build and push your images:

```bash
APP_VERSION=0.0.0
REGISTRY=iad.ocir.io/testing

podman build -f src/client/Dockerfile -t ${REGISTRY}/ai-optimizer-client:${APP_VERSION} .
podman build -f src/server/Dockerfile -t ${REGISTRY}/ai-optimizer-server:${APP_VERSION} .

podman push ${REGISTRY}/ai-optimizer-client:${APP_VERSION}
podman push ${REGISTRY}/ai-optimizer-server:${APP_VERSION}
```

In values, either provide fully-qualified repositories:

```yaml
server:
  image:
    repository: iad.ocir.io/testing/ai-optimizer-server
    tag: "0.0.0"
client:
  image:
    repository: iad.ocir.io/testing/ai-optimizer-client
    tag: "0.0.0"
```

Or set `global.imageRegistry` and keep component repositories unqualified:

```yaml
global:
  imageRegistry: iad.ocir.io/testing
server:
  image:
    repository: ai-optimizer-server
client:
  image:
    repository: ai-optimizer-client
```

## Minimal Values

{{% notice style="code" title="Production Hygiene" icon="shield" %}}
Inline credentials in a values file get committed by accident. Create Kubernetes Secrets and reference them by name; the chart auto-generates a strong password where one isn't supplied and keeps it across upgrades via `helm.sh/resource-policy: keep`.
{{% /notice %}}

Create the namespace and pre-shared Secrets up front:

```bash
kubectl create namespace ai-optimizer
kubectl -n ai-optimizer create secret generic optimizer-api-key \
  --from-literal=apiKey="$(openssl rand -base64 32)"
kubectl -n ai-optimizer create secret generic optimizer-cookie-key \
  --from-literal=cookieSecret="$(openssl rand -base64 32)"
```

Example values:

```yaml
global:
  api:
    secretName: optimizer-api-key

client:
  cookieSecretName: optimizer-cookie-key
```

For throwaway tests you can pass values inline with `--set-string`, but don't ship credentials that way.

## Database Modes

The chart supports four database modes:

| Mode | Use When | Notes |
| --- | --- | --- |
| `SIDB-FREE` | You want the chart to run Oracle Database Free in the cluster. | Requires a pinned `server.database.image.tag`. |
| `ADB-FREE` | You want the chart to run Autonomous Database Free in the cluster. | Requires a pinned `server.database.image.tag`. |
| `ADB-S` | You have an OCI Autonomous Database. | Requires the Oracle Database Operator CRD in the cluster. |
| `OTHER` | You bring an external Oracle Database connection string. | The chart renders only the application DB Secret and server wiring. |

If `server.database.type` is empty, no database resources or DB environment variables are rendered.

Container database example:

```yaml
server:
  database:
    type: SIDB-FREE
    image:
      repository: container-registry.oracle.com/database/free
      tag: "23.26.1.0"
```

External database example:

```yaml
server:
  database:
    type: OTHER
    other:
      dsn: "mydbhost.example.com:1521/MYSERVICE"
    authn:
      secretName: db-authn
```

ADB-S example:

```yaml
server:
  database:
    type: ADB-S
    oci:
      ocid: "ocid1.autonomousdatabase.oc1..."
    adb:
      serviceName: myadb_low
    authn:
      secretName: db-authn
  ociConfig:
    oke: true
    region: us-ashburn-1
```

`server.database.authn` configures the application database credentials. `server.database.privAuthn` configures privileged credentials used by chart-managed user setup for database modes that need it.

{{% icon star %}} More information about configuring the database can be found in the [Database Configuration]({{% relref "/client/configuration/databases" %}}) documentation.

## OCI And Model Secrets

OCI settings live under `server.ociConfig`. On OKE, prefer workload identity:

```yaml
server:
  ociConfig:
    oke: true
    region: us-ashburn-1
```

For non-OKE installs, create a Kubernetes Secret from an OCI config file:

```bash
python helm/scripts/oci_config.py --config ~/.oci/config --namespace ai-optimizer
```

Then reference it with `server.ociConfig.fileSecretName: oci-config-file` (or whatever you passed to `--secret-name`).

Third-party model credentials are provided by Secret references. For example:

```yaml
server:
  models:
    openai:
      secretName: openai-secret
      secretKey: apiKey
```

{{% icon star %}} More information about OCI configuration can be found in the [OCI Configuration]({{% relref "/client/configuration/oci" %}}) documentation.

### Split & Embed Source Lock

To pin the Split & Embed tab's OCI source compartment (and optionally bucket) for every user of the deployment, set first-class values under `client.oci`:

```yaml
client:
  oci:
    sourceBucketCompartmentId: ocid1.compartment.oc1..aaaa
    sourceBucketName: my-corpus-bucket
```

The compartment is the anchor — `sourceBucketName` alone has no effect. See [Environment Variables]({{% relref "/configuration#oci-object-storage-source-lock" %}}) for the matching `AIO_OCI_SOURCE_BUCKET_*` variables and runtime behavior.

## Observability

OpenTelemetry export is controlled by `server.otel.enabled`. You can point it at your own collector:

```yaml
server:
  otel:
    enabled: true
    endpoint: https://otel.example.com:4317
    headersSecret:
      name: otel-headers
```

Or deploy the in-chart SigNoz stack:

```yaml
signoz:
  enabled: true
server:
  otel:
    enabled: true
    insecure: true
```

{{% notice style="code" title="Observability is Hungry" icon="fire" %}}
The observability collector, query service, and UI together want several GiB of memory — plan accordingly. Persistent Volume Claims (PVCs) are preserved on uninstall; set `global.cleanupPVCs=true` only when you intentionally want telemetry storage deleted.
{{% /notice %}}

{{% icon star %}} More information about reading traces and dashboards can be found in the [Observability]({{% relref "/observability" %}}) documentation.

## Environment Overrides

Most application settings should be configured through chart values or Kubernetes Secrets. If you need to provide application `.env` content, use the chart-managed env Secret blocks:

```yaml
server:
  envSecret:
    content:
      AIO_LOG_LEVEL: INFO
      AIO_GENAI_REGION: us-chicago-1
```

Pod environment variables rendered by the chart take precedence over `.env` content. See [Environment Variables]({{% relref "/configuration" %}}) for application variables.

## Optional Components

The web client is enabled by default. Disable it with:

```yaml
client:
  enabled: false
```

Ollama is disabled by default. Enable it only on a cluster with suitable CPU, memory, and preferably GPU scheduling:

```yaml
ollama:
  enabled: true
  resources:
    limits:
      nvidia.com/gpu: 1
```

## Deploy

Install from the published chart repository:

```bash
helm repo add ai-optimizer https://oracle.github.io/ai-optimizer/helm
helm repo update

helm upgrade --install ai-optimizer ai-optimizer/ai-optimizer \
  --namespace ai-optimizer \
  --create-namespace \
  --values values.yaml
```

Install from a local checkout:

```bash
cd helm
helm dependency build

helm upgrade --install ai-optimizer . \
  --namespace ai-optimizer \
  --create-namespace \
  --values values.yaml
```

Use `helm lint` and `helm template` before applying changes:

```bash
helm lint . --values values.yaml
helm template ai-optimizer . --namespace ai-optimizer --values values.yaml
```

## Kind Example

Kind is useful for chart development and quick local testing.

```bash
kind create cluster -n ai-optimizer

APP_VERSION=0.0.0
podman build -f src/client/Dockerfile -t localhost/ai-optimizer-client:${APP_VERSION} .
podman build -f src/server/Dockerfile -t localhost/ai-optimizer-server:${APP_VERSION} .

kind load docker-image localhost/ai-optimizer-client:${APP_VERSION} -n ai-optimizer
kind load docker-image localhost/ai-optimizer-server:${APP_VERSION} -n ai-optimizer
```

Create `values-kind.yaml`:

```yaml
server:
  image:
    repository: localhost/ai-optimizer-server
    tag: "0.0.0"
  database:
    type: SIDB-FREE
    image:
      repository: container-registry.oracle.com/database/free
      tag: "23.26.1.0"

client:
  image:
    repository: localhost/ai-optimizer-client
    tag: "0.0.0"
```

Deploy:

```bash
helm upgrade --install ai-optimizer ./helm \
  --namespace ai-optimizer \
  --create-namespace \
  --set-string global.api.apiKey="$(openssl rand -base64 32)" \
  --set-string client.cookieSecret="$(openssl rand -base64 32)" \
  --values values-kind.yaml
```

Check the release and open the client:

```bash
kubectl -n ai-optimizer get pods
kubectl -n ai-optimizer port-forward svc/ai-optimizer-client-http 8501:8501
```

Open `http://localhost:8501`.

## What's Next?

With {{< short_app_ref >}} up and running, the natural next steps are:

- Swap the in-cluster Free database for an [`ADB-S`](#database-modes) instance on OCI.
- Turn on autoscaling (`server.autoscaling.enabled`) once you're past the single-pod prototype.
- Enable [observability](#observability) with the bundled SigNoz stack or your own collector.
- Front the client and server with [TLS]({{% relref "/advanced/tls" %}}).
