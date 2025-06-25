# Oracle AI Optimizer and Toolkit Helm Chart

## Secret Pre-Requisites

This Helm Chart requires three Kubernetes Secrets to be created prior to installing:

### Registry Credentials

**Note**: This requirement is deprecated in OCI/OKE when using the IaC from opentofu: [Credential Provider](https://github.com/oracle-devrel/oke-credential-provider-for-ocir)

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: regcred
type: kubernetes.io/dockerconfigjson
stringData:
  .dockerconfigjson: ...
```

Example:

```bash
podman login iad.ocir.io -u <username>
kubectl create secret docker-registry regcred --from-file=.dockerconfigjson=/run/user/1002/containers/auth.json
```

### Model API Keys

Example:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: client-api-keys
type: Opaque
stringData:
  api_server_key: ...
  openai_api_key: ...
  pplx_api_key: ...
```

### Database Authentication

Example:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: optimizerdb-authn
type: Opaque
stringData:
  password: ...
  service: ...
  username: ...
```

## Install

```bash
helm upgrade --install ai-optimizer .
```

## Uninstall

```bash
helm uninstall ai-optimizer
```
