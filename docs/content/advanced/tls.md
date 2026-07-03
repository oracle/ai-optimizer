+++
title = 'TLS / HTTPS'
weight = 10
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore streamlit sslcertfile sslkeyfile certfile
-->

Both the {{% short_app_ref %}} **Server** and **Client** can be configured to serve over **HTTPS** instead of plain **HTTP**.

There are three options for each component:

- **None** — No TLS; traffic is plain HTTP. This is the default and is fine for local desktop experimentation.
- **Self-signed** — Let the {{% short_app_ref %}} create a certificate on the fly and reuse it across restarts. Traffic is encrypted, but since it is a self-signed certificate, browsers will show a "not secure" warning until you tell them to trust it. Great for development instances.
- **Provided** — Bring your own certificate and key, usually one issued by a trusted certificate authority. This is what you'll want for production.

## Server

The server TLS environment variables are documented under [Server]({{% relref "/configuration#server" %}}) in Environment Variables.

### Self-Signed Certificate (Quick Start)

The simplest way to enable HTTPS is to set `AIO_SERVER_SSL=true` without providing certificate files.  The entrypoint will automatically generate a self-signed certificate at startup:

```bash
# In .env.dev (or .env.prd, etc.)
AIO_SERVER_SSL=true
```

These variables can also be exported directly in the shell before running the entrypoint.

Then start the server:

```bash
./src/entrypoint.py server
```

The generated certificate and key are stored in `tmp/ssl/` (relative to the `src/` directory) and are reused across restarts.

### User-Provided Certificates

For production or corporate environments where a trusted certificate authority (CA) is available, provide the paths to the certificate and key files:

```bash
# In .env.dev (or .env.prd, etc.)
AIO_SERVER_SSL=true
AIO_SERVER_SSL_CERT_FILE=/path/to/cert.pem
AIO_SERVER_SSL_KEY_FILE=/path/to/key.pem
```

These variables can also be exported directly in the shell before running the entrypoint.

Then start the server:

```bash
./src/entrypoint.py server
```

The certificate should be PEM-encoded and may include intermediate CA certificates in the chain.

### Helm Chart

When deploying with the Helm chart, set `server.ssl.enabled` to `true`.  This automatically sets the `AIO_SERVER_SSL` environment variable on the pod and switches the health probes to HTTPS.

To use auto-generated self-signed certificates (simplest option):

```yaml
server:
  ssl:
    enabled: true
```

To use certificates from a Kubernetes Secret, provide `certFile`/`keyFile` paths and mount the Secret into the container:

```yaml
server:
  ssl:
    enabled: true
    certFile: "/app/tls/cert.pem"
    keyFile: "/app/tls/key.pem"

  volumes:
    - name: tls
      secret:
        secretName: server-tls

  volumeMounts:
    - name: tls
      mountPath: "/app/tls"
      readOnly: true
```

## Client

The client TLS environment variables are documented under [Client]({{% relref "/configuration#client" %}}) in Environment Variables.

### Self-Signed Certificate (Quick Start)

The simplest way to enable HTTPS is to set `AIO_CLIENT_SSL=true` without providing certificate files.  The entrypoint will automatically generate a self-signed certificate at startup:

```bash
# In .env.dev (or .env.prd, etc.)
AIO_CLIENT_SSL=true
```

These variables can also be exported directly in the shell before running the entrypoint.

Then start the client:

```bash
./src/entrypoint.py client
```

The generated certificate and key are stored in `tmp/ssl/` (relative to the `src/` directory) and are reused across restarts.

{{% notice style="code" title="Browser Warning" icon="circle-info" %}}
Self-signed certificates will trigger a browser security warning on first access.  Accept the warning to proceed, or install the generated `tmp/ssl/cert.pem` as a trusted certificate in your browser or operating system.
{{% /notice %}}

### User-Provided Certificates

For production or corporate environments where a trusted certificate authority (CA) is available, provide the paths to the certificate and key files:

```bash
# In .env.dev (or .env.prd, etc.)
AIO_CLIENT_SSL=true
AIO_CLIENT_SSL_CERT_FILE=/path/to/cert.pem
AIO_CLIENT_SSL_KEY_FILE=/path/to/key.pem
```

These variables can also be exported directly in the shell before running the entrypoint.

Then start the client:

```bash
./src/entrypoint.py client
```

The certificate should be PEM-encoded and may include intermediate CA certificates in the chain.

### Helm Chart

When deploying with the Helm chart, set `client.ssl.enabled` to `true`.  This automatically sets the `AIO_CLIENT_SSL` environment variable on the pod and switches the health probes to HTTPS.

To use auto-generated self-signed certificates (simplest option):

```yaml
client:
  ssl:
    enabled: true
```

To use certificates from a Kubernetes Secret, provide `certFile`/`keyFile` paths and mount the Secret into the container:

```yaml
client:
  ssl:
    enabled: true
    certFile: "/app/tls/cert.pem"
    keyFile: "/app/tls/key.pem"

  volumes:
    - name: tls
      secret:
        secretName: client-tls

  volumeMounts:
    - name: tls
      mountPath: "/app/tls"
      readOnly: true
```
