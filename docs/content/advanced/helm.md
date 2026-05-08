+++
title = 'Helm Chart'
weight = 5
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore ashburn sidb myadb ocid ollama autonomousdatabase mxbai subcharts tolerations
-->

The {{< full_app_ref >}} was specifically designed to run on infrastructure supporting microservices architecture, including [Kubernetes](https://kubernetes.io/).  A [Helm](https://helm.sh/) Chart is provided to make the deployment easier.

To use the {{< short_app_ref >}} Helm Chart:
  1. [Build, Tag, and Push](#images) the {{< short_app_ref >}} Images
  1. [Configure](#configure-valuesyaml) the [values.yaml](https://github.com/oracle/ai-optimizer/blob/main/helm/values.yaml)
  1. [Deploy!](#deploy)

{{% notice style="code" title="Go Local" icon="laptop" %}}
A full example of running the {{< short_app_ref >}} in a local Kubernetes cluster using Docker container "nodes" via the [Kind](https://kind.sigs.k8s.io/) tool is [provided](#kind-example).
{{% /notice %}}


### Images

You will need to build the {{< short_app_ref >}} container images and stage them in a container registry, such as the [OCI Container Registry](https://docs.oracle.com/en-us/iaas/Content/Registry/Concepts/registryoverview.htm) (**OCIR**).

1. Download the latest release:
{{< latest_release >}}

1. Uncompress the release in a new directory.  For example:

   ```bash
   mkdir ai-optimizer
   tar zxf ai-optimizer-src.tar.gz -C ai-optimizer

   cd ai-optimizer
   ```

1. Build the {{< short_app_ref >}} images:
   
   _Note:_ Depending on the Kubernetes worker node architecture, you may need to specify `--arch amd64` or `--arch arm64`

    ```bash
    podman build -f src/client/Dockerfile -t ai-optimizer-client:latest .

    podman build -f src/server/Dockerfile -t ai-optimizer-server:latest .
    ```

1. Tag the {{< short_app_ref >}} images:

    Tag the images as required by your container registry.  For example, if using the **OCIR** registry in _US East (Ashburn)_ with a namespace of `testing`:

    ```bash
    podman tag ai-optimizer-client:latest iad.ocir.io/testing/ai-optimizer-client:latest
    podman tag ai-optimizer-server:latest iad.ocir.io/testing/ai-optimizer-server:latest
    ```

1. Push the {{< short_app_ref >}} images:

    Push the images to your container registry.  If required, login to the registry first.
    For example, if using the **OCIR** registry in _US East (Ashburn)_ with a namespace of `testing`:

    ```bash
    podman login iad.ocir.io

    podman push iad.ocir.io/testing/ai-optimizer-client:latest
    podman push iad.ocir.io/testing/ai-optimizer-server:latest
    ```

    You will use the URL for the pushed images when [configuring](#configure-valuesyaml) the [values.yaml](https://github.com/oracle/ai-optimizer/blob/main/helm/values.yaml).


### Configure values.yaml

The [values.yaml](https://github.com/oracle/ai-optimizer/blob/main/helm/values.yaml) allows you to customize the deployment by overriding settings such as image versions, resource requests, service configurations, and more. You can modify this file directly or supply your own overrides during installation using the -f or --set flags.

Only a subset of the most important settings are documented here, review the `values.yaml` file for more configuration options.

#### Global Settings

The `global:` sections contains values that are shared across the chart and its subcharts.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| global.api | object | | Either provide the 'apiKey' directly or provide a secretName referring to an existing Secret containing the API key. |
| global.api.apiKey | string | `""` | Key for making API calls to the server. Recommended to supply at command line or use the secretName to avoid storing in the values file. Example: "abcd1234opt5678" |
| global.api.secretKey | string | `"apiKey"` | Key name inside the Secret that contains the API key when secretName defined. |
| global.api.secretName | string | `""` | Name of the Secret that stores the API key. This allows you to keep the API key out of the values file and manage it securely via Secrets. Example: "optimizer-api-keys" |
| global.baseUrlPath | string | `"/"` | URL path appended to the host. Example: "/test" results in URLs like http://hostname/test/... |
| global.env | string | `"prd"` | Environment name. Controls which .env file pydantic-settings reads (`.env.{env}`) and the mount path for envSecret. |

---

#### Server Settings

The `server:` sections contains values that are used to configure the {{< short_app_ref >}} API Server.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| server.replicaCount | int | `1` | Number of desired pod replicas for the Deployment when autoscaling is disabled |
| server.maxClients | int | `64` | Max number of distinct client sessions cached in memory (LRU eviction beyond this) |
| server.image.repository | string | `"localhost/ai-optimizer-server"` | Image Repository |
| server.image.tag | string | `"latest"` | Image Tag |
| server.imagePullSecrets | list | `[]` | Secret name containing image pull secrets |

##### Server Database Settings

Configure the Oracle Database used by the {{< short_app_ref >}} API Server.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| server.database.type | string | `""` | Either SIDB-FREE, ADB-FREE, ADB-S, or OTHER |
| server.database.image | object | | For SIDB-FREE/ADB-FREE, location of the image and its tag; Exclude for ADB-S/OTHER |
| server.database.image.repository | string | `""` | For SIDB-FREE/ADB-FREE, repository location of the image |
| server.database.image.tag | string | `"latest"` | For SIDB-FREE/ADB-FREE, tag of the image |
| server.database.oci | Optional | | For ADB-S, OCID of the Autonomous Database Exclude for SIDB-FREE/ADB-FREE/OTHER |
| server.database.oci.ocid | string | `""` | OCID of the Autonomous Database |
| server.database.other | Optional | | For OTHER, connection details for external database |
| server.database.other.dsn | string | `""` | Full DSN string (e.g: host:port/service) - Either dsn OR (host+port+serviceName) |
| server.database.other.host | string | `""` | Database host (required if dsn not provided) |
| server.database.other.port | string/int | `""` | Database port (required if dsn not provided) |
| server.database.other.serviceName | string | `""` | Database service name (required if dsn not provided) |
| server.database.authN | Required |  | Application User Authentication/Connection Details If defined, used to create the user defined in the authN secret |
| server.database.authN.secretName | string | `"db-authn"` | Name of Secret containing the authentication/connection details |
| server.database.authN.usernameKey | string | `"username"` | Key in secretName containing the username |
| server.database.authN.passwordKey | string | `"password"` | Key in secretName containing the password |
| server.database.authN.serviceKey | string | `"service"` | Key in secretName containing the connection service name |
| server.database.privAuthN | Optional |  | Privileged User Authentication/Connection Details If defined, used to create the user defined in the authN secret |
| server.database.privAuthN.secretName | string | `"db-priv-authn"` | secretName containing privileged user (i.e. ADMIN/SYSTEM) password |
| server.database.privAuthN.usernameKey | string | `"username"` | Key in secretName containing the username |
| server.database.privAuthN.passwordKey | string | `"password"` | Key in secretName containing the password |


###### Examples

**SIDB-FREE**

A containerized single-instance Oracle Database:
```yaml
  database:
    type: "SIDB-FREE"
    image:
      repository: container-registry.oracle.com/database/free
      tag: latest
```

**ADB-FREE**

A containerized Autonomous Oracle Database:
```yaml
  database:
    type: "ADB-FREE"
    image:
      repository: container-registry.oracle.com/database/adb-free
      tag: latest
```

**ADB-S**

A pre-deployed Oracle Autonomous Database (_requires_ the [OraOperator](https://github.com/oracle/oracle-database-operator) to be installed in the cluster):

```yaml
  database:
    type: "ADB-S"
    oci:
      ocid: "ocid1.autonomousdatabase.oc1..."
```

**OTHER**

An external or bring-your-own Oracle Database:

Option 1 - Using full DSN string:
```yaml
  database:
    type: "OTHER"
    other:
      dsn: "mydbhost.example.com:1521/MYSERVICE"
```

Option 2 - Using individual components:
```yaml
  database:
    type: "OTHER"
    other:
      host: "mydbhost.example.com"
      port: "1521"
      serviceName: "MYSERVICE"
```

##### Server Oracle Cloud Infrastructure Settings

Configure Oracle Cloud Infrastructure used by the {{< short_app_ref >}} API Server for access to Object Storage and OCI GenAI Services.


| Key | Type | Default | Description |
|-----|------|---------|-------------|
| server.oci_config.oke | bool | `false` | Enable Workload Identity Principals (WIP) (must be implemented) |
| server.oci_config.tenancy | string | `""` | Tenancy OCID.  Required when specifying keySecretName. |
| server.oci_config.user | string | `""` | User OCID.  Required when specifying keySecretName. |
| server.oci_config.fingerprint | string | `""` | Fingerprint.  Required when specifying keySecretName. |
| server.oci_config.region | string | `""` | Region. Required when oke is true. |
| server.oci_config.fileSecretName | string | `""` | Secret containing an OCI config file and the key_file(s). Use the [scripts/oci_config.py](https://github.com/oracle/ai-optimizer/blob/main/helm/scripts/oci_config.py) script to help create the secret based on an existing ~.oci/config file |
| server.oci_config.keySecretName | string | `""` | Secret containing a single API key corresponding to above tenancy configuration This used by OraOperator when not running in OKE |

###### Examples

**OKE with Workload Identity Principles**
```yaml
  oci_config:
    oke: true
    region: "us-ashburn-1"
```

**Secret generated using scripts/oci_config.py**
```yaml
  oci_config:
    fileSecretName: "oci-config-file"
```

**Manual Configuration with Secret containing API Key**
```yaml
  oci_config:
    tenancy: "ocid1.tenancy.oc1.."
    user: "ocid1.user.oc1.."
    fingerprint: "e8:65:45:4a:85:4b:6c:.."
    region: "us-ashburn-1"
    keySecretName: my-api-key
```

##### Server 3rd-Party Model Settings

Configure 3rd-Party AI Models used by the {{< short_app_ref >}} API Server.  Create Kubernetes Secret(s) to hold the 3rd-Party API Keys.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| server.models.cohere | object | `{"secretKey":"apiKey","secretName":""}` | Cohere API Key |
| server.models.openAI | object | `{"secretKey":"apiKey","secretName":""}` | OpenAI API Key |
| server.models.perplexity | object | `{"secretKey":"apiKey","secretName":""}` | Perplexity API Key |

##### Server OpenTelemetry Configuration

Wires the running pod to an OTLP collector. Two deployment shapes:

1. **Bring-your-own collector** — point `endpoint` at a separately-deployed SigNoz, Jaeger, Tempo, or vendor agent.
2. **In-chart SigNoz** — set `signoz.enabled=true` (see [SigNoz subchart](#signoz-subchart) below). The chart then deploys SigNoz as a subchart and `server.otel.endpoint` defaults to the in-cluster collector URL automatically; explicit values still win.

See [Observability]({{% relref "/observability" %}}) for the broader workflow and [SigNoz Quickstart]({{% relref "/observability/signoz" %}}) for the standalone-Compose path.

The published image already includes the OTel SDK; setting `enabled: true` is sufficient to start exporting.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| server.otel.enabled | bool | `false` | Master switch. When false, no `OTEL_*` env vars are rendered and the server's telemetry init is a no-op. |
| server.otel.endpoint | string | `""` | OTLP receiver URL applied to all signals. Required when `enabled=true` unless `tracesEndpoint` is set, or `tracesExporter` is `"console"` or `"none"`. `logsEndpoint` alone does **not** satisfy this — log export piggybacks on the traces path. Example: `http://signoz-otel-collector.observability.svc.cluster.local:4317` |
| server.otel.tracesEndpoint | string | `""` | Per-signal endpoint override for traces. Empty inherits `endpoint`. |
| server.otel.logsEndpoint | string | `""` | Per-signal endpoint override for logs. Empty inherits `endpoint`. |
| server.otel.protocol | string | `""` | Wire protocol for all signals. One of `grpc` (port 4317) or `http/protobuf` (port 4318). Empty falls back to the SDK default of `grpc`. |
| server.otel.tracesProtocol | string | `""` | Per-signal protocol override for traces. Empty inherits `protocol`. |
| server.otel.logsProtocol | string | `""` | Per-signal protocol override for logs. Empty inherits `protocol`. |
| server.otel.insecure | bool | `false` | Skip TLS verification for OTLP gRPC. Required for plaintext in-cluster collectors (typical for SigNoz with no TLS sidecar). |
| server.otel.headers | string | `""` | Comma-separated `k=v` headers for vendor auth (e.g. SigNoz cloud API key). Mutually exclusive with `headersSecret`. Prefer `headersSecret` for any value containing a credential. |
| server.otel.headersSecret.name | string | `""` | Name of a pre-existing Secret containing OTLP auth headers. Mutually exclusive with the plaintext `headers` field. |
| server.otel.headersSecret.key | string | `"headers"` | Key within the Secret that holds the headers value. |
| server.otel.serviceName | string | `""` | Override the service name shown in the backend. Empty uses the application default (`ai-optimizer-server`). |
| server.otel.resourceAttributes | object | `{}` | Map of string→string resource attributes attached to every span. Values are percent-encoded before joining, so commas/spaces/equals signs round-trip correctly. `deployment.environment` is already populated from `global.env`; only override here if you need a different value. |
| server.otel.tracesExporter | string | `""` | Comma-separated exporter list. Supported tokens: `otlp`, `console`, `none`. `none` is the explicit opt-out and must stand alone. Empty uses the application default (`otlp`). |
| server.otel.logsEnabled | bool | `false` | Application log export to OTLP. Disabled by default for privacy: log records can include chat content. Enable only against backends whose retention/access policy is approved for application payloads. |
| server.otel.logsExporter | string | `""` | Comma-separated log exporter list. Supported: `otlp` (ship logs) or `none` (explicit suppression). `console` is not implemented for logs. Use `none` to keep tracing while suppressing logs even when `logsEnabled=true`. |
| server.otel.sampler | string | `""` | Trace sampler name (e.g. `parentbased_traceidratio`). Empty uses the SDK default (`parentbased_always_on`). |
| server.otel.samplerArg | string | `""` | Sampler argument (e.g. ratio for `parentbased_traceidratio`). Numeric values are preserved. |
| server.otel.extraEnv | list | `[]` | Free-form additional env vars passed through to the pod (e.g. `OTEL_BSP_*`, `OTEL_PROPAGATORS`). Each entry is `{name, value}` or `{name, valueFrom}`. Scalar values are stringified for the Kubernetes API. |

###### Examples

**SigNoz, in-cluster, plaintext gRPC**

```yaml
server:
  otel:
    enabled: true
    endpoint: http://signoz-otel-collector.observability.svc.cluster.local:4317
    insecure: true
    resourceAttributes:
      service.namespace: ai-optimizer
```

**Vendor backend with API-key header from a Secret**

```bash
kubectl create secret generic otel-headers \
  --from-literal=headers="signoz-access-token=<token>" \
  -n ai-optimizer
```

```yaml
server:
  otel:
    enabled: true
    endpoint: https://ingest.example.com:4317
    headersSecret:
      name: otel-headers
```

**Local debug — console traces, no collector**

```yaml
server:
  otel:
    enabled: true
    tracesExporter: console
```

##### SigNoz Subchart

Deploys [SigNoz](https://signoz.io) alongside the application as a Helm subchart (from the official `https://charts.signoz.io` repository). Two switches must both be on for the server to actually export telemetry — `signoz.enabled=true` (deploys the collector and UI) and `server.otel.enabled=true` (turns on the application-side exporter). When both are set and `server.otel.endpoint` is empty, the server's OTLP endpoint auto-defaults to the in-cluster collector URL, so the operator only needs the two boolean flags. See [Wiring `server.otel`](#wiring-serverotel) for the full minimal values overlay.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| signoz.enabled | bool | `false` | Master switch. When `true`, the SigNoz subchart's resources render alongside the application. The chart pins SigNoz **0.122.0** in `Chart.yaml`. |

The `signoz` block passes through to the upstream chart; any key valid in [`SigNoz/charts`](https://github.com/SigNoz/charts/blob/main/charts/signoz/values.yaml) can be overridden here, e.g.:

```yaml
signoz:
  enabled: true
  otelCollector:
    service:
      type: ClusterIP   # default; LoadBalancer/NodePort also work
    replicaCount: 1
```

###### Prerequisite

Run the following two commands against the chart directory once before `helm install` / `helm package`:

```bash
helm repo add --force-update signoz https://charts.signoz.io
helm dependency build
```

The dependency tarball is **not** committed; `build` pulls it from `charts.signoz.io` using the digest in `Chart.lock`. The `helm repo add` is required because `build` resolves by repository URL against `helm repo list`, not by fetching the URL directly. Without these, `helm install` fails with either `no repository definition for https://charts.signoz.io` or `found in Chart.yaml, but missing in charts/ directory`.

###### Resource expectations

The default SigNoz deploy runs ClickHouse, the query service, the frontend, and the OTel collector. Plan for **~3-5 GiB RAM minimum**. The Kind example below does not enable SigNoz for this reason; enable it only on a cluster sized to host it.

###### After install

The bundled `NOTES.txt` prints the port-forward and bootstrap commands. To summarize:

```bash
# UI
kubectl port-forward -n <namespace> svc/<release>-signoz 8080:8080
# Browse to http://localhost:8080 — first visit prompts for admin account

# Load curated dashboards/alerts (after at least one chat completion has been ingested):
observability/signoz/bootstrap-signoz.py \
  --host http://localhost:8080 \
  --email <admin-email>
```

See [`observability/signoz/README.md`](https://github.com/oracle/ai-optimizer/blob/main/observability/signoz/README.md) for why a real chat request is required before bootstrap, and how to round-trip dashboard changes back to the repository.

###### Wiring `server.otel`

`signoz.enabled=true` does **not** turn on the server's exporter — `server.otel.enabled` remains the master switch for the application side. Both must be set:

```yaml
signoz:
  enabled: true
server:
  otel:
    enabled: true
    insecure: true   # the in-chart collector serves plaintext gRPC
```

When `signoz.enabled=true` but `server.otel.enabled=false`, the install proceeds (SigNoz can host telemetry from other workloads in the cluster) and `NOTES.txt` prints a warning.

---

##### Server Environment Configuration

Application settings can be provided via a `.env.{env}` file (where `{env}` is set by `global.env`, default `prd`) stored as a Kubernetes Secret. The application uses [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) to read the file directly. Pod environment variables always take precedence over values in the `.env` file. See [Configuration](/env_config/) for available variables.

You can either reference a pre-existing Secret or let Helm create one from key-value pairs:

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| server.envSecret.secretName | string | `""` | Name of a pre-existing Secret containing the `.env.{env}` file content. When set, Helm will not create a Secret. |
| server.envSecret.secretKey | string | `"server.env"` | Key within the Secret that holds the file content. |
| server.envSecret.content | object | `{}` | Key-value pairs for Helm to generate the Secret. Ignored when `secretName` is set. |

###### Examples

**User-provided Secret**

Create the Secret yourself and reference it:
```bash
kubectl create secret generic my-server-env \
  --from-file=server.env=.env.prd \
  -n ai-optimizer
```

```yaml
server:
  envSecret:
    secretName: "my-server-env"
    secretKey: "server.env"
```

**Helm-generated Secret**

Let Helm create the Secret from inline values:
```yaml
server:
  envSecret:
    content:
      AIO_LOG_LEVEL: INFO
      AIO_DB_POOL_SIZE: "5"
      AIO_GENAI_COMPARTMENT_ID: "ocid1.compartment..."
      AIO_GENAI_REGION: "us-chicago-1"
```

---
#### Client Settings

The `client:` sections contains values that are used to configure the {{< short_app_ref >}} frontend web client.

The frontend web client can be disabled by setting `global.enableClient` to `false`.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| client.replicaCount | int | `1` | Number of desired pod replicas for the Deployment when autoscaling is disabled |
| client.imagePullSecrets | list | `[]` | Secret name containing image pull secrets |
| client.image.repository | string | `"localhost/ai-optimizer-client"` | Image Repository |
| client.image.tag | string | `"latest"` | Image Tag |
| client.cookieSecret | string | `""` | Signing key for the client's XSRF cookies. Either provide `cookieSecret` inline (Helm creates the Secret) or provide `cookieSecretName` referring to an existing Secret. Exactly one must be set; install fails otherwise. Must be shared across all replicas. Recommended to supply at command line or via `cookieSecretName` to avoid storing in the values file. Example: "abcd1234opt5678" |
| client.cookieSecretName | string | `""` | Name of a pre-existing Secret containing the cookie signing key. Rotation contract: after rotating the Secret's contents in place, run `helm upgrade` so the chart reads the new value and rolls the client Deployment. Example: "optimizer-cookie-keys" |
| client.cookieSecretKey | string | `"cookieSecret"` | Key name inside the Secret that contains the cookie signing key. |

##### Client Features Settings

Disable specific {{< short_app_ref >}} in the frontend web client.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| client.features.disableTestbed | bool | `false` | Disable the Test Bed |
| client.features.disableApi | bool | `false` | Disable the API Server Administration/Monitoring |
| client.features.disableTools | bool | `false` | Disable Tools such as Prompt Engineering and Split/Embed |
| client.features.disableDbCfg | bool | `false` | Disable Tools Database Configuration |
| client.features.disableModelCfg | bool | `false` | Disable Tools Model Configuration |
| client.features.disableOciCfg | bool | `false` | Disable OCI Configuration |
| client.features.disableSettings | bool | `false` | Disable the Import/Export of Settings |

##### Client Environment Configuration

The client supports the same `.env.{env}` Secret mechanism as the [server](#server-environment-configuration). Pod environment variables always take precedence.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| client.envSecret.secretName | string | `""` | Name of a pre-existing Secret containing the `.env.{env}` file content. When set, Helm will not create a Secret. |
| client.envSecret.secretKey | string | `"client.env"` | Key within the Secret that holds the file content. |
| client.envSecret.content | object | `{}` | Key-value pairs for Helm to generate the Secret. Ignored when `secretName` is set. |

###### Examples

**Helm-generated Secret**
```yaml
client:
  envSecret:
    content:
      AIO_LOG_LEVEL: INFO
```

#### Ollama Settings

The `ollama:` section contains values that are used to automatically install [Ollama](https://ollama.com/) and optionally pull models.

The Ollama functionality can be enabled by setting `global.enableOllama` to true.

It is recommended only to enable this functionality when you have access to a GPU worker node.  Use the scheduling and resource constraints to ensure the Ollama resources are running on that GPU.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| ollama.replicaCount | int | `1` | Number of desired pod replicas for the Deployment |
| ollama.image.repository | string | `"docker.io/ollama/ollama"` | Image Repository |
| ollama.image.tag | string | `"latest"` | Image Tag |
| ollama.models.enabled | bool | `true` | Enable automatic pulling of models |
| ollama.models.modelPullList | list | `["qwen3:8b","mxbai-embed-large"]` | List of models to automatically pull |
| ollama.resources | object | `{}` | Requests and limits for the container. Often used to ensure pod is running on a GPU worker |
| ollama.nodeSelector | object | `{}` | Constrain pods to specific nodes Often used to ensure pod is running on a GPU worker |
| ollama.affinity | object | `{}` | Rules for scheduling pods Often used to ensure pod is running on a GPU worker |
| ollama.tolerations | list | `[]` | For scheduling pods on tainted nodes Often used to ensure pod is running on a GPU worker |

---
### Deploy

Once your `values.yaml` has been configured and you have a Kubernetes cluster available.  Deploy the Helm Chart:

1. Add the Helm Repository
```sh
helm repo add ai-optimizer https://oracle.github.io/ai-optimizer/helm
```

2. Apply the `values.yaml` file:
```sh
helm upgrade --install ai-optimizer \
  ai-optimizer/ai-optimizer \
  --namespace ai-optimizer \
  --values values.yaml
```

---
## Kind Example

Give the **Helm Chart** a spin using a locally installed [Kind](https://kind.sigs.k8s.io/) for experimenting and development.

1. Install Kind locally

    There are many ways to install **Kind**, refer to the [official documentation](https://kind.sigs.k8s.io/docs/user/quick-start/#installation) for more information.

1. Create a Cluster

    ```sh
    kind create cluster -n ai-optimizer
    ```

1. Build the Images

    [Build](#images) the {{< short_app_ref >}} Images per the above instructions.  There's no need to tag or push them.

1. Load the images into the Kind cluster

    ```sh
    kind load docker-image ai-optimizer-client:latest -n ai-optimizer
    kind load docker-image ai-optimizer-server:latest -n ai-optimizer
    ```

    {{% notice style="tip" title="Top Tip" icon="thumbs-up" %}}
    Pull and load the database and ollama images before deploying the Helm Chart.  This will speed up the deployment:

  ```plaintext
  podman pull docker.io/ollama/ollama:latest
  podman pull container-registry.oracle.com/database/free:latest

  kind load docker-image docker.io/ollama/ollama:latest -n ai-optimizer
  kind load docker-image container-registry.oracle.com/database/free:latest -n ai-optimizer
  ```
    {{% /notice %}}

1. (Optional) Configure for Oracle Cloud Infrastructure

    If you already have an OCI API configuration file, use the [scripts/oci_config.py](https://github.com/oracle/ai-optimizer/blob/main/helm/scripts/oci_config.py) helper script to turn it into a secret for OCI connectivity:

    ```sh
    kubectl create namespace ai-optimizer
    python scripts/oci_config.py --namespace ai-optimizer
    ```
    Run the output to create the secret

1. Create a values-kind.yaml file

    **OCI**: Remove the `server.oci_config` specification if skipping the above optional step.

    ```yaml
    server:
      replicaCount: 1
      image:
        repository: localhost/ai-optimizer-server
        tag: latest
      database:
        type: "SIDB-FREE"
        image:
          repository: container-registry.oracle.com/database/free
          tag: latest
    client:
      replicaCount: 1
      image:
        repository: localhost/ai-optimizer-client
        tag: latest
    ollama:
      enabled: true
      replicaCount: 1
      models:
        enabled: true
    ```

1. Add the Helm Repository
```sh
helm repo add ai-optimizer https://oracle.github.io/ai-optimizer/helm
```

1. Deploy the Helm Chart

    ```sh
    helm upgrade \
      --create-namespace \
      --namespace ai-optimizer \
      --install ai-optimizer . \
      --set global.api.apiKey="my-api-key" \
      --set client.cookieSecret="$(openssl rand -base64 32)" \
      --values ./values-kind.yaml
    ```

1. Wait for all Pods to be "Running"

    ```sh
    kubectl -n ai-optimizer get all
    ```

    The Ollama pod may take some time as it pulls models.

1. Create a port-forward to access the environment:

    ```sh
    kubectl -n ai-optimizer port-forward services/ai-optimizer-client-http 8501:80
    ```

1. Open your browser to `http://localhost:8501`