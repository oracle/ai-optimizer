+++
title = 'Helm Chart'
weight = 5
+++

<!--
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
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
   
   _Note:_ Depending on the Kubernetes worker node architecture, you may need to specify `--arch amd64` or `--arch aarm64`

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

---

#### Server Settings

The `server:` sections contains values that are used to configure the {{< short_app_ref >}} API Server.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| server.replicaCount | int | `1` | Number of desired pod replicas for the Deployment when autoscaling is disabled |
| server.image.repository | string | `"localhost/ai-optimizer-server"` | Image Repository |
| server.image.tag | string | `"latest"` | Image Tag |
| server.imagePullSecrets | list | `[]` | Secret name containing image pull secrets |

##### Server Database Settings

Configure the Oracle Database used by the {{< short_app_ref >}} API Server.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| server.database.type | string | `""` | Either SIDB-FREE, ADB-FREE, or ADB-S |
| server.database.image | object | | For SIDB-FREE/ADB-FREE, location of the image and its tag; Exclude for ADB-S |
| server.database.image.repository | string | `""` | For SIDB-FREE/ADB-FREE, repository location of the image |
| server.database.image.tag | string | `"latest"` | For SIDB-FREE/ADB-FREE, tag of the image |
| server.database.authN | Required |  | Application User Authentication/Connection Details If defined, used to create the user defined in the authN secret |
| server.database.authN.secretName | string | `"db-authn"` | Name of Secret containing the authentication/connection details |
| server.database.authN.usernameKey | string | `"username"` | Key in secretName containing the username |
| server.database.authN.passwordKey | string | `"password"` | Key in secretName containing the password |
| server.database.authN.serviceKey | string | `"service"` | Key in secretName containing the connection service name |
| server.database.privAuthN | Optional |  | Privileged User Authentication/Connection Details If defined, used to create the user defined in the authN secret |
| server.database.privAuthN.secretName | string | `"db-priv-authn"` | secretName containing privileged user (i.e. ADMIN/SYSTEM) password |
| server.database.privAuthN.passwordKey | string | `"password"` | Key in secretName containing the password |
| server.database.oci_db | Optional | | For ADB-S, OCID of the Autonomous Database Exclude for SIDB-FREE/ADB-FREE |
| server.database.oci_db.ocid | string | `""` | OCID of the DB |


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
    oci_db: 
      ocid: "ocid1.autonomousdatabase.oc1..."
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
| ollama.models.modelPullList | list | `["llama3.1","mxbai-embed-large"]` | List of models to automatically pull |
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