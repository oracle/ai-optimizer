+++
title = 'Configuration'
weight = 10
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore genai vllm pplx
-->

The {{< full_app_ref >}} can be configured using environment files (`.env.*`) to pre-configure settings at startup. This is optional — the application will start and function without any environment file, but features like RAG, settings persistence, and the Testbed require access to a "CORE" [database](client/configuration/databases/).

## How It Works

On startup, the {{< short_app_ref >}} loads variables from a `.env.{AIO_ENV}` file located in the `src/` directory. The `AIO_ENV` environment variable determines which file is loaded, defaulting to `dev` if not set.

| `AIO_ENV` Value | File Loaded |
|---|---|
| `dev` (default) | `src/.env.dev` |
| `prd` | `src/.env.prd` |
| _custom_ | `src/.env.{custom}` |

Variables set in the `.env.*` file will **not** overwrite existing environment variables. This means exported environment variables and container `ENV` directives always take precedence.

### Precedence

The {{< short_app_ref >}} follows this precedence order (highest to lowest):

1. **Exported environment variables** (e.g. `export AIO_DB_USERNAME=demo`)
2. **Variables** in the `.env.*` file
3. **Config file values** (e.g. `~/.oci/config`)
4. **Application defaults**

Additionally, non-prefixed environment variables take precedence over their `AIO_` equivalents for database (`DB_USERNAME`, `DB_PASSWORD`, `DB_DSN`, `DB_WALLET_LOCATION`) and OCI CLI (`OCI_CLI_AUTH`, `OCI_CLI_TENANCY`, etc.) settings.

## Getting Started

To create an environment file, copy the provided example:

```bash
cp src/.env.example src/.env.dev
```

Edit `src/.env.dev` and uncomment/set the values you need.

{{% notice style="code" title="No configuration required" icon="circle-info" %}}
<!-- Hard-coding AI Optimizer to avoid unsafe HTML, this is an exception -->
The **AI Optimizer** will start without any `.env.*` file or environment variables set. However, to persist settings across restarts and to enable features like RAG and the Testbed, at a minimum a [database](/client/configuration/databases/) should be configured.
{{% /notice %}}

## Available Variables

The following variables can be set in the `.env.*` file. All variables use the `AIO_` prefix.

### Authentication

| Variable | Description | Default |
|---|---|---|
| `AIO_API_KEY` | API key for authenticating requests to the API Server. If not set, a key is auto-generated at startup and can be obtained from the [API Server](client/api_server/) page. | _(auto-generated)_ |

### Database

Database variables configure the CORE database connection. For more details, see [Database Configuration](client/configuration/databases/).

| Variable | Description |
|---|---|
| `AIO_DB_USERNAME` | Database username |
| `AIO_DB_PASSWORD` | Database password |
| `AIO_DB_DSN` | Connection string or TNS alias |
| `AIO_DB_WALLET_PASSWORD` | _(Optional)_ Wallet password for mTLS |
| `AIO_DB_WALLET_LOCATION` | _(Optional)_ Path to the wallet directory for mTLS connections |
| `AIO_DB_POOL_SIZE` | Connection pool size (default: `5`) |

### Logging

| Variable | Description | Default |
|---|---|---|
| `AIO_LOG_LEVEL` | Python logging level | `INFO` |

### Server

| Variable | Description | Default |
|---|---|---|
| `AIO_SERVER_URL` | URL the client uses to reach the API Server | _(auto-detected)_ |
| `AIO_SERVER_URL_PREFIX` | URL path prefix for the API Server (e.g. `/optimizer`) | _(none)_ |
| `AIO_SERVER_PORT` | API Server listen port | `8000` |
| `AIO_SERVER_SSL` | Enable TLS for the API Server | `false` |
| `AIO_SERVER_SSL_CERT_FILE` | Path to TLS certificate (PEM). If SSL is enabled without this, a self-signed certificate is generated. | _(none)_ |
| `AIO_SERVER_SSL_KEY_FILE` | Path to TLS private key (PEM) | _(none)_ |
| `AIO_SERVER_READY_TIMEOUT` | Seconds the client waits for the API Server to become ready at startup | `180` |

### Client

| Variable | Description | Default |
|---|---|---|
| `AIO_CLIENT_ADDRESS` | Client listen address | `localhost` |
| `AIO_CLIENT_URL_PREFIX` | URL path prefix for the Client | _(none)_ |
| `AIO_CLIENT_PORT` | Client listen port | `8501` |
| `AIO_CLIENT_COOKIE_SECRET` | Secret for client session cookies | _(none)_ |
| `AIO_CLIENT_SSL` | Enable TLS for the Client | `false` |
| `AIO_CLIENT_SSL_CERT_FILE` | Path to TLS certificate (PEM) | _(none)_ |
| `AIO_CLIENT_SSL_KEY_FILE` | Path to TLS private key (PEM) | _(none)_ |

### OCI CLI Overrides

These override the DEFAULT OCI profile. For more details, see [OCI Configuration](client/configuration/oci/).

| Variable | Description |
|---|---|
| `AIO_OCI_CLI_AUTH` | Auth type (e.g. `api_key`, `instance_principal`) |
| `AIO_OCI_CLI_TENANCY` | Tenancy OCID |
| `AIO_OCI_CLI_REGION` | OCI region |
| `AIO_OCI_CLI_USER` | User OCID |
| `AIO_OCI_CLI_FINGERPRINT` | API key fingerprint |
| `AIO_OCI_CLI_KEY_FILE` | Path to private key (PEM) |
| `AIO_OCI_CLI_KEY_CONTENT` | Inline private key content |
| `AIO_OCI_CLI_PASSPHRASE` | Private key passphrase |
| `AIO_OCI_CLI_SECURITY_TOKEN_FILE` | Path to security token file |

### NL2SQL

| Variable | Description | Default |
|---|---|---|
| `AIO_SQLCL_HOME` | Override the SQLcl connection store directory. Also accepts `SQLCL_HOME`. | _(temporary directory)_ |

### OCI GenAI

| Variable | Description |
|---|---|
| `AIO_GENAI_COMPARTMENT_ID` | Compartment OCID for OCI GenAI inference |
| `AIO_GENAI_REGION` | Region for the OCI GenAI service endpoint |

### Model Overrides

These set API keys or URLs to automatically enable models at startup.

| Variable | Description |
|---|---|
| `AIO_COHERE_API_KEY` | Cohere API key |
| `AIO_OPENAI_API_KEY` | OpenAI API key |
| `AIO_PPLX_API_KEY` | Perplexity AI API key |
| `AIO_ON_PREM_OLLAMA_URL` | Ollama API URL (e.g. `http://127.0.0.1:11434`) |
| `AIO_ON_PREM_HF_URL` | HuggingFace TEI URL (e.g. `http://127.0.0.1:8080`) |
| `AIO_ON_PREM_VLLM_URL` | vLLM API URL (e.g. `http://localhost:8000/v1`) |
