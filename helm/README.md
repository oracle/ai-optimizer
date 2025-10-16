# Oracle AI Optimizer Helm Chart

This Helm chart deploys the Oracle AI Optimizer, a comprehensive GenAI/RAG platform combining a Streamlit client, FastAPI server, and Oracle AI Database integration.

## Overview

The Oracle AI Optimizer enables developers and data scientists to explore Large Language Models (LLMs) with Retrieval-Augmented Generation (RAG) capabilities, leveraging Oracle AI Database for vector search and SelectAI features.

**Architecture Components:**
- **Server**: FastAPI-based REST API server with LangGraph agent orchestration
- **Client**: Streamlit web UI for interactive chat, testing, and configuration
- **Database**: Support for Oracle Autonomous Database (ADB-S, ADB-FREE) and Single Instance Database (SIDB-FREE)
- **Ollama** (optional): Local LLM deployment for on-premises inference

## Prerequisites

- Kubernetes 1.18+
- Helm 3.0+
- Oracle Database (one of):
  - Autonomous Database Shared (ADB-S) - requires OCI account
  - Containerized Autonomous Database FREE (ADB-FREE)
  - Containerized Single Instance Database FREE (SIDB-FREE)
  - Bring-Your-Own Database with AI Vector Search enabled
- (Optional) Oracle Database Operator for ADB-S integration
- (Optional) Storage class for persistent volumes (if using containerized databases)

## Quick Start

### 1. Generate API Key

Create a secure API key for server-client authentication:

```bash
# Generate random API key
export API_KEY=$(openssl rand -base64 32)
```

### 2. Basic Installation (with Ollama and SIDB-FREE)

```bash
helm install ai-optimizer . \
  --set global.api.apiKey="$API_KEY"
```

### 3. Access the Application

```bash
# Port forward the client (Streamlit UI)
kubectl port-forward svc/ai-optimizer-client 8501:8501

# Visit in browser
open http://localhost:8501
```

## Installation Examples

### Example 1: Local Development (KinD with SIDB-FREE)

```bash
helm install ai-optimizer . \
  --set global.api.apiKey="$API_KEY" \
  --values examples/values-kind-sidb-free.yaml
```

### Example 2: Local Development (KinD with ADB-FREE)

```bash
helm install ai-optimizer . \
  --set global.api.apiKey="$API_KEY" \
  --values examples/values-kind-adb-free.yaml
```

### Example 3: Production with External ADB-S

First, create necessary secrets:

```bash
# Create database authentication secret
kubectl create secret generic db-authn \
  --from-literal=username=AI_OPTIMIZER \
  --from-literal=password='YourSecurePassword123!' \
  --from-literal=service='adb_service_high'

# Create OCI config secret (for database operator)
# Use the helper script to create from your ~/.oci/config
python scripts/oci_config.py --config ~/.oci/config --secret-name oci-config-file
```

Then install:

```bash
helm install ai-optimizer . \
  --set global.api.apiKey="$API_KEY" \
  --set server.database.type="ADB-S" \
  --set server.database.oci.ocid="ocid1.autonomousdatabase.oc1..." \
  --set server.database.authN.secretName="db-authn" \
  --set server.oci_config.fileSecretName="oci-config-file" \
  --set server.oci_config.region="us-ashburn-1"
```

### Example 4: Production with OpenAI Integration

```bash
# Create OpenAI API key secret
kubectl create secret generic openai-secret \
  --from-literal=apiKey='sk-...'

helm install ai-optimizer . \
  --set global.api.apiKey="$API_KEY" \
  --set server.models.openAI.secretName="openai-secret" \
  --set server.database.type="ADB-S" \
  --set server.database.oci.ocid="ocid1.autonomousdatabase..."
```

### Example 5: High Availability with Autoscaling

```bash
helm install ai-optimizer . \
  --set global.api.apiKey="$API_KEY" \
  --set server.autoscaling.enabled=true \
  --set server.autoscaling.minReplicas=2 \
  --set server.autoscaling.maxReplicas=10 \
  --set server.resources.requests.cpu=1000m \
  --set server.resources.requests.memory=2Gi \
  --set server.resources.limits.cpu=2000m \
  --set server.resources.limits.memory=4Gi \
  --set client.autoscaling.enabled=true \
  --set client.autoscaling.minReplicas=2 \
  --set client.autoscaling.maxReplicas=5
```

### Example 6: Ingress with TLS

```bash
# Create TLS secret
kubectl create secret tls ai-optimizer-tls \
  --cert=path/to/tls.crt \
  --key=path/to/tls.key

helm install ai-optimizer . \
  --set global.api.apiKey="$API_KEY" \
  --set server.ingress.enabled=true \
  --set server.ingress.className="nginx" \
  --set server.ingress.tls[0].hosts[0]="api.example.com" \
  --set server.ingress.tls[0].secretName="ai-optimizer-tls" \
  --set client.ingress.enabled=true \
  --set client.ingress.className="nginx" \
  --set client.ingress.tls[0].hosts[0]="app.example.com" \
  --set client.ingress.tls[0].secretName="ai-optimizer-tls"
```

## Configuration

### Global Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `global.api.apiKey` | API key for server authentication (required if secretName not set) | `""` |
| `global.api.secretName` | Name of existing Secret containing API key | `""` |
| `global.api.secretKey` | Key within Secret containing API key | `"apiKey"` |
| `global.baseUrlPath` | Base URL path for all services | `"/"` |

**Note**: You must specify either `global.api.apiKey` OR `global.api.secretName`, but not both.

### Server Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `server.replicaCount` | Number of server pods (when autoscaling disabled) | `1` |
| `server.image.repository` | Server container image repository | `localhost/ai-optimizer-server` |
| `server.image.tag` | Server container image tag | `latest` |
| `server.image.pullPolicy` | Image pull policy | `IfNotPresent` |
| `server.service.type` | Kubernetes service type | `ClusterIP` |
| `server.resources` | CPU/Memory resource requests and limits | `{}` |

#### Server Autoscaling

| Parameter | Description | Default |
|-----------|-------------|---------|
| `server.autoscaling.enabled` | Enable HorizontalPodAutoscaler | `false` |
| `server.autoscaling.minReplicas` | Minimum replicas | `1` |
| `server.autoscaling.maxReplicas` | Maximum replicas | `100` |
| `server.autoscaling.targetCPUUtilizationPercentage` | Target CPU % | `80` |
| `server.autoscaling.targetMemoryUtilizationPercentage` | Target Memory % | `80` |

#### Server Database Configuration

| Parameter | Description | Default | Options |
|-----------|-------------|---------|---------|
| `server.database.type` | Type of Oracle Database | `""` | `SIDB-FREE`, `ADB-FREE`, `ADB-S`, `OTHER` |
| `server.database.image.repository` | Container image for SIDB/ADB-FREE | `""` | See examples |
| `server.database.image.tag` | Container image tag | `latest` | |
| `server.database.oci.ocid` | ADB-S OCID (for ADB-S only) | `""` | |
| `server.database.other.host` | Database host (for OTHER only) | `""` | Required for OTHER |
| `server.database.other.port` | Database port (for OTHER only) | `""` | Required for OTHER |
| `server.database.other.service_name` | Database service name (for OTHER only) | `""` | Required for OTHER |
| `server.database.authN.secretName` | Secret with DB credentials | `"db-authn"` | Auto-generated if not exists |
| `server.database.authN.usernameKey` | Key for username in secret | `"username"` | |
| `server.database.authN.passwordKey` | Key for password in secret | `"password"` | |
| `server.database.authN.serviceKey` | Key for connection string in secret | `"service"` | |
| `server.database.privAuthN.secretName` | Secret with privileged user password | `"db-priv-authn"` | For user creation |
| `server.database.privAuthN.passwordKey` | Key for privileged password | `"password"` | |

**Database Types:**
- **SIDB-FREE**: Oracle AI Database Free (containerized single instance)
- **ADB-FREE**: Autonomous Oracle AI Database Free (containerized)
- **ADB-S**: Autonomous Database Shared (managed OCI service)
- **OTHER**: External/bring-your-own database (requires host, port, and service_name)

#### Server OCI Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `server.oci_config.oke` | Enable OKE Workload Identity Principals | `false` |
| `server.oci_config.tenancy` | OCI Tenancy OCID | `""` |
| `server.oci_config.user` | OCI User OCID | `""` |
| `server.oci_config.fingerprint` | OCI API Key Fingerprint | `""` |
| `server.oci_config.region` | OCI Region | `""` |
| `server.oci_config.fileSecretName` | Secret with OCI config file and keys | `""` |
| `server.oci_config.keySecretName` | Secret with single API key (for operator) | `""` |

Use `scripts/oci_config.py` to create the `fileSecretName` secret from your `~/.oci/config`.

#### Server Model Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `server.models.openAI.secretName` | Secret containing OpenAI API key | `""` |
| `server.models.openAI.secretKey` | Key within secret | `"apiKey"` |
| `server.models.perplexity.secretName` | Secret containing Perplexity API key | `""` |
| `server.models.perplexity.secretKey` | Key within secret | `"apiKey"` |
| `server.models.cohere.secretName` | Secret containing Cohere API key | `""` |
| `server.models.cohere.secretKey` | Key within secret | `"apiKey"` |

#### Server Ingress

| Parameter | Description | Default |
|-----------|-------------|---------|
| `server.ingress.enabled` | Enable Ingress resource | `false` |
| `server.ingress.className` | IngressClass name | `nginx` |
| `server.ingress.annotations` | Ingress annotations | See values.yaml |
| `server.ingress.tls` | TLS configuration | `[]` |

#### Server Probes

| Parameter | Description | Default |
|-----------|-------------|---------|
| `server.livenessProbe.enabled` | Enable liveness probe | `true` |
| `server.livenessProbe.initialDelaySeconds` | Initial delay | `10` |
| `server.livenessProbe.periodSeconds` | Check period | `30` |
| `server.livenessProbe.timeoutSeconds` | Timeout | `5` |
| `server.livenessProbe.failureThreshold` | Failure threshold | `3` |
| `server.readinessProbe.enabled` | Enable readiness probe | `true` |
| `server.readinessProbe.initialDelaySeconds` | Initial delay | `10` |
| `server.readinessProbe.periodSeconds` | Check period | `15` |

### Client Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `client.enabled` | Enable client deployment | `true` |
| `client.replicaCount` | Number of client pods | `1` |
| `client.image.repository` | Client container image | `localhost/ai-optimizer-client` |
| `client.image.tag` | Client container image tag | `latest` |
| `client.service.type` | Kubernetes service type | `ClusterIP` |

#### Client Feature Flags

| Parameter | Description | Default |
|-----------|-------------|---------|
| `client.features.disableTestbed` | Disable Q&A testbed feature | `false` |
| `client.features.disableApi` | Disable API server monitoring | `false` |
| `client.features.disableTools` | Disable prompt engineering & embed tools | `false` |
| `client.features.disableDbCfg` | Disable database configuration | `false` |
| `client.features.disableModelCfg` | Disable model configuration | `false` |
| `client.features.disableOciCfg` | Disable OCI configuration | `false` |
| `client.features.disableSettings` | Disable settings import/export | `false` |

#### Client Autoscaling

Same structure as server autoscaling (see above).

#### Client Ingress

| Parameter | Description | Default |
|-----------|-------------|---------|
| `client.ingress.enabled` | Enable Ingress resource | `false` |
| `client.ingress.className` | IngressClass name | `nginx` |
| `client.ingress.annotations` | Ingress annotations | See values.yaml |
| `client.ingress.tls` | TLS configuration | `[]` |

### Ollama Configuration (Optional Local LLM)

| Parameter | Description | Default |
|-----------|-------------|---------|
| `ollama.enabled` | Enable Ollama deployment | `false` |
| `ollama.replicaCount` | Number of Ollama pods | `1` |
| `ollama.image.repository` | Ollama image | `docker.io/ollama/ollama` |
| `ollama.image.tag` | Ollama image tag | `latest` |
| `ollama.models.enabled` | Auto-pull models on startup | `true` |
| `ollama.models.modelPullList` | List of models to pull | `[llama3.1, mxbai-embed-large]` |
| `ollama.resources` | Resource requests/limits (GPU support) | `{}` |

**Note**: For GPU support, set:
```yaml
ollama:
  resources:
    limits:
      nvidia.com/gpu: 1
  nodeSelector:
    accelerator: nvidia-tesla-t4
  tolerations:
    - key: nvidia.com/gpu
      operator: Exists
```

## Advanced Configuration

### Using External Secrets

Instead of providing `global.api.apiKey` directly, reference an existing secret:

```bash
kubectl create secret generic my-api-secret --from-literal=apiKey="your-secure-key"

helm install ai-optimizer . \
  --set global.api.secretName="my-api-secret"
```

### Custom Volume Mounts

Add custom volumes and volume mounts:

```yaml
server:
  volumes:
    - name: custom-config
      configMap:
        name: my-custom-config
  volumeMounts:
    - name: custom-config
      mountPath: /app/config
      readOnly: true
```

### Node Affinity and Tolerations

Schedule pods on specific nodes:

```yaml
server:
  nodeSelector:
    disktype: ssd
    zone: us-west-1a
  affinity:
    podAntiAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        - labelSelector:
            matchExpressions:
              - key: app.kubernetes.io/component
                operator: In
                values:
                  - server
          topologyKey: "kubernetes.io/hostname"
  tolerations:
    - key: "dedicated"
      operator: "Equal"
      value: "ai-workloads"
      effect: "NoSchedule"
```

### Persistent Storage for Databases

When using SIDB-FREE or ADB-FREE, configure persistent volumes:

```yaml
server:
  database:
    type: "SIDB-FREE"
    image:
      repository: container-registry.oracle.com/database/free
    persistence:
      enabled: true
      storageClass: "fast-ssd"
      size: 50Gi
```

## Upgrading

### Standard Upgrade

```bash
helm upgrade ai-optimizer . \
  --set global.api.apiKey="$API_KEY" \
  --reuse-values
```

### Upgrade with New Values

```bash
helm upgrade ai-optimizer . \
  --values my-custom-values.yaml
```

### View Pending Changes

```bash
helm diff upgrade ai-optimizer . --values my-custom-values.yaml
```

## Uninstalling

```bash
helm uninstall ai-optimizer
```

**Note**: Secrets with `helm.sh/resource-policy: keep` annotation (like database credentials) will be retained. Delete them manually if needed:

```bash
kubectl delete secret ai-optimizer-db-authn
```

## Troubleshooting

### Check Pod Status

```bash
kubectl get pods -l app.kubernetes.io/name=ai-optimizer
```

### View Server Logs

```bash
kubectl logs -l app.kubernetes.io/component=server -f
```

### View Client Logs

```bash
kubectl logs -l app.kubernetes.io/component=client -f
```

### Check Database Connection

```bash
# Exec into server pod
kubectl exec -it deployment/ai-optimizer-server -- /bin/sh

# Test database connection
python -c "import oracledb; print('DB driver loaded')"
```

### Common Issues

#### 1. API Key Not Set

**Error**: `You must specify either global.api.apiKey or global.api.secretName`

**Solution**: Provide API key via `--set global.api.apiKey="..."` or reference existing secret.

#### 2. Database Connection Fails

**Error**: `ORA-12154: TNS:could not resolve the connect identifier`

**Solution**:
- For ADB-S: Verify wallet secret is created by database operator
- For SIDB/ADB-FREE: Check database pod is running and service is accessible
- Verify connection string in secret: `kubectl get secret db-authn -o yaml`

#### 3. Image Pull Errors

**Error**: `ImagePullBackOff`

**Solution**:
- For local images: Ensure images are built and available in cluster
- For Oracle Registry: Images are built on the fly; buildkit pod should be completed before further troubleshooting

#### 4. Probes Failing

**Error**: `Readiness probe failed`

**Solution**: Increase probe timeouts or disable:
```yaml
server:
  readinessProbe:
    enabled: false
# Or increase thresholds
  readinessProbe:
    failureThreshold: 10
    timeoutSeconds: 30
```

#### 5. OCI Operator CRD Not Found

**Error**: `no matches for kind "AutonomousDatabase"`

**Solution**: Install Oracle Database Operator:
```bash
kubectl apply -f https://raw.githubusercontent.com/oracle/oracle-database-operator/main/oracle-database-operator.yaml
```

## Security Considerations

1. **API Keys**: Always use Kubernetes Secrets, never commit API keys to version control
2. **Database Passwords**: Auto-generated passwords are pseudo-random; for production, provide your own secure passwords
3. **TLS**: Enable TLS on Ingress resources for production
4. **Network Policies**: Consider adding NetworkPolicies to restrict pod-to-pod communication
5. **Pod Security**: Chart enforces security best practices:
   - Non-root execution (`runAsUser: 10001`)
   - Read-only root filesystem
   - Capabilities dropped
6. **RBAC**: For ADB-S integration, ensure proper OCI IAM policies are configured

## Values Schema

For a complete list of all configuration options, see:
- [values.yaml](./values.yaml) - Default values with inline documentation
- [examples/](./examples/) - Example configurations

## Support

- GitHub Issues: https://github.com/oracle/ai-optimizer/issues
- Documentation: https://github.com/oracle/ai-optimizer
- License: Universal Permissive License v1.0

## Chart Metadata

- **Type**: application
- **Maintainer**: Oracle (obaas_ww@oracle.com)
