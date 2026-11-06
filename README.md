# Oracle AI Optimizer and Toolkit

If you find this project useful, please consider giving it a [⭐](https://github.com/oracle/ai-optimizer/stargazers)!

<!-- spell-checker:ignore AgentSpec Docling FastAPI FAISS LangGraph LiteLLM OpenTelemetry OpenTofu pyagentspec SigNoz streamlit Uvicorn venv vLLM setuptools -->
[![Test Suite](https://github.com/oracle/ai-optimizer/actions/workflows/pytest.yml/badge.svg)](https://github.com/oracle/ai-optimizer/actions/workflows/pytest.yml)
[![Validate IaC](https://github.com/oracle/ai-optimizer/actions/workflows/opentofu.yml/badge.svg)](https://github.com/oracle/ai-optimizer/actions/workflows/opentofu.yml)
[![Validate Container Images](https://github.com/oracle/ai-optimizer/actions/workflows/image_smoke.yml/badge.svg)](https://github.com/oracle/ai-optimizer/actions/workflows/image_smoke.yml)
[![Deploy Documentation](https://github.com/oracle/ai-optimizer/actions/workflows/documentation.yml/badge.svg)](https://github.com/oracle/ai-optimizer/actions/workflows/documentation.yml)

The **Oracle AI Optimizer and Toolkit** (the **AI Optimizer**) is an open-source platform for building, testing, and evaluating GenAI applications. Its agentic runtime grounds model responses at request time in authoritative private and sensitive data that remains outside the model's training knowledge and under your control in **Oracle AI Database**.

The Server exposes a REST API and Model Context Protocol (MCP) endpoint. An optional Streamlit web client provides configuration and experimentation. Portable AgentSpec definitions are loaded into a LangGraph runtime for an LLM-only agent, an NL2SQL agent backed by SQLcl MCP, and a Vector Search RAG flow. A combined router coordinates the NL2SQL and Vector Search routes.

## Technology Stack

- **Application:** Python, Streamlit client, and FastAPI/Uvicorn server.
- **AI orchestration:** LangChain, LangGraph, LiteLLM, AgentSpec/pyagentspec, and Model Context Protocol (MCP).
- **Oracle integration:** Oracle AI Database Vector Search, Oracle Deep Data Security, SQLcl MCP, OCI, OCI GenAI, and OCI Object Storage.
- **RAG and evaluation:** Docling, OracleDB/LangChain vector integrations, Giskard v3 testbed checks, and FAISS-backed local vector workflows.
- **Model providers and runtimes:** OCI GenAI, OpenAI-compatible APIs, OpenAI, Cohere, Perplexity, Ollama, Hugging Face, vLLM, and TGI-style hosted runtimes.
- **Deployment and operations:** Docker/Podman, Kubernetes, Helm, OpenTofu infrastructure automation, OpenTelemetry, and SigNoz.

## AI Optimizer Features

- [Run LLM-only and tool-enabled agents and flows](https://oracle.github.io/ai-optimizer/docs/client/chatbot/)
- [Configure language and embedding models](https://oracle.github.io/ai-optimizer/docs/client/configuration/models/)
- [Split and embed documents for Vector Search](https://oracle.github.io/ai-optimizer/docs/client/tools/split-embed/)
- [Refresh vector stores from OCI Object Storage](https://oracle.github.io/ai-optimizer/docs/client/tools/split-embed/)
- [Manage system prompts](https://oracle.github.io/ai-optimizer/docs/client/tools/prompts/)
- [Evaluate generated or existing Q&A datasets](https://oracle.github.io/ai-optimizer/docs/client/testbed/)
- [Apply Oracle Deep Data Security policies](https://oracle.github.io/ai-optimizer/docs/client/tools/dds/)
- [Inspect portable AgentSpec definitions](https://oracle.github.io/ai-optimizer/docs/client/configuration/agentspec/)
- Integrate external applications through the [REST API](https://oracle.github.io/ai-optimizer/docs/server/api-examples/intro/) or [MCP endpoint](https://oracle.github.io/ai-optimizer/docs/guides/mcp-clients/)

## Getting Started

Run the **AI Optimizer** on a developer workstation, on premises, or in a cloud environment. Supported deployment options include bare metal, containers, Oracle Cloud Infrastructure (OCI), and Kubernetes.

For guided installation and configuration, see the [documentation](https://oracle.github.io/ai-optimizer/docs/intro/).

### Prerequisites

- [Oracle AI Database](https://oracle.github.io/ai-optimizer/docs/guides/database/), including [Oracle AI Database Free](https://www.oracle.com/database/free/).
- Access to a language model to run agents and flows
- Access to an embedding model for RAG and Vector Search
- [SQLcl](https://oracle.github.io/ai-optimizer/docs/guides/sqlcl-mcp-server/) for NL2SQL
- [uv](https://docs.astral.sh/uv/) for bare-metal installation
- A container runtime such as Docker or Podman for container installation

Language and embedding models can use third-party APIs or run on premises. Oracle recommends GPUs for models hosted on premises.

#### Bare-Metal Installation

To run the application on bare metal, download the [source](https://github.com/oracle/ai-optimizer):

1. Create the project environment and install the application:

   ```bash
   uv sync --all-extras
   ```

1. Optionally create an environment file to preconfigure the application:

   ```bash
   cp src/.env.example src/.env.dev
   ```

   Edit `src/.env.dev` and set the required `AIO_DB_*` values for the Oracle AI Database connection, or complete the local database setup page when the client first starts.

1. Start the AI Optimizer Client:

   ```bash
   uv run python src/entrypoint.py client
   ```

1. Navigate to `http://localhost:8501`.

1. [Configure](https://oracle.github.io/ai-optimizer/docs/client/configuration/) the **AI Optimizer**.

#### Container Installation

To run the application in a container, download the [source](https://github.com/oracle/ai-optimizer):

1. Build the all-in-one image.

   _Note:_ macOS Silicon users may need to specify `--arch amd64`.

   ```bash
   podman build -f src/Dockerfile -t localhost/ai-optimizer-aio:dev .
   ```

1. Start the container:

   ```bash
   podman run -v ai-optimizer-data:/app/data -p 8501:8501 -it --rm localhost/ai-optimizer-aio:dev
   ```

1. Navigate to `http://localhost:8501`.

1. Complete the required Oracle AI Database setup page. A successful configuration is stored in the `ai-optimizer-data` container volume.

1. [Configure](https://oracle.github.io/ai-optimizer/docs/client/configuration/) the **AI Optimizer**.

#### Got OCI?

The **AI Optimizer** can be deployed in Oracle Cloud Infrastructure (OCI) using Infrastructure as Code (IaC).

Choose a virtual machine or Oracle Kubernetes Engine deployment, both with an Oracle Autonomous Database:

[![Deploy to Oracle Cloud][magic_button]][magic_arch_stack]

For more information, see the [IaC documentation](https://oracle.github.io/ai-optimizer/docs/advanced-guides/iac/).

## Contributing

This project welcomes contributions from the community. Before submitting a pull request, please [review our contribution guide](./CONTRIBUTING.md).

## Security

Please consult the [security guide](./SECURITY.md) for our responsible security vulnerability disclosure process.

## License

Copyright (c) 2024 Oracle and/or its affiliates.
Released under the Universal Permissive License v1.0 as shown at [https://oss.oracle.com/licenses/upl/](https://oss.oracle.com/licenses/upl/)

See [LICENSE](./LICENSE.txt) for more details.


[magic_button]: https://oci-resourcemanager-plugin.plugins.oci.oraclecloud.com/latest/deploy-to-oracle-cloud.svg
[magic_arch_stack]: https://cloud.oracle.com/resourcemanager/stacks/create?zipUrl=https://github.com/oracle/ai-optimizer/releases/latest/download/ai-optimizer-iac.zip
