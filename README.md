# Oracle AI Optimizer and Toolkit

<!-- spell-checker:ignore streamlit, venv, setuptools -->
![Test Status](https://github.com/oracle/ai-optimizer/actions/workflows/pytest.yml/badge.svg)
![IaC Status](https://github.com/oracle/ai-optimizer/actions/workflows/opentofu.yml/badge.svg)
![Build Status](https://github.com/oracle/ai-optimizer/actions/workflows/image_smoke.yml/badge.svg)

## Description

The **Oracle AI Optimizer and Toolkit** (the **AI Optimizer**) provides a streamlined environment where developers and data scientists can explore the potential of Generative Artificial Intelligence (GenAI) combined with Retrieval-Augmented Generation (RAG) capabilities. By integrating **Oracle AI Database** VectorSearch and SelectAI, the Sandbox enables users to enhance existing Large Language Models (LLMs) through RAG.

## AI Optimizer Features

- [Configuring Embedding and Chat Models](https://oracle.github.io/ai-optimizer/client/configuration/model_config)
- [Splitting and Embedding Documentation](https://oracle.github.io/ai-optimizer/client/tools/split_embed)
- [Modifying System Prompts (Prompt Engineering)](https://oracle.github.io/ai-optimizer/client/tools/prompt_eng)
- [Experimenting with **LLM** Parameters](https://oracle.github.io/ai-optimizer/client/chatbot)
- [Testbed for auto-generated or existing Q&A datasets](https://oracle.github.io/ai-optimizer/client/testbed)

## Getting Started

The **AI Optimizer** is available to install in your own environment, which may be a developer's desktop, on-premises data center environment, or a cloud provider. It can be run either on bare-metal, within a container, or in a Kubernetes Cluster.

For more information, including more details on **Setup and Configuration** please visit the [documentation](https://oracle.github.io/ai-optimizer).

### Prerequisites

- Oracle AI Database incl. Oracle AI Database Free
- Python 3.11 (for running Bare-Metal)
- Container Runtime e.g. docker/podman (for running in a Container)
- Access to an Embedding and Chat Model:
  - API Keys for Third-Party Models
  - On-Premises Models<sub>\*</sub>

<sub>\*Oracle recommends running On-Premises Models on hardware with GPUs. For more information, please review the [Infrastructure](https://oracle.github.io/ai-optimizer/infrastructure) documentation.</sub>

#### Bare-Metal Installation

To run the application on bare-metal; download the [source](https://github.com/oracle/ai-optimizer):

1. Create and activate a Python Virtual Environment:

   ```bash
   python3.11 -m venv .venv --copies
   source .venv/bin/activate
   pip3.11 install --upgrade pip wheel setuptools uv
   ```

1. Install the Python modules:

   ```bash
   uv pip install -e ".[all]"
   ```

1. Start Streamlit:

   ```bash
   cd src/
   streamlit run launch_client.py --server.port 8501
   ```

1. Navigate to `http://localhost:8501`.

1. [Configure](https://oracle.github.io/ai-optimizer/client/configuration) the **AI Optimizer**.

#### Container Installation

To run the application in a container; download the [source](https://github.com/oracle/ai-optimizer):

1. Build the all-in-one image.

   _Note:_ MacOS Silicon users may need to specify `--arch amd64`

   ```bash
   podman build -f src/Dockerfile -t ai-optimizer-aio .
   ```

1. Start the Container:

   ```bash
   podman run -p 8501:8501 -it --rm ai-optimizer-aio
   ```

1. Navigate to `http://localhost:8501`.

1. [Configure](https://oracle.github.io/ai-optimizer/client/configuration/index.html) the **AI Optimizer**.

#### Got OCI?

The **AI Optimizer** can be deployed in Oracle Cloud Infrastructure (OCI) using Infrastructure as Code (IaC).

Choose either a light-weight Virtual Machine or robust Oracle Kubernetes Engine deployment, both with an Oracle Autonomous Database:  
[![Deploy to Oracle Cloud][magic_button]][magic_arch_stack]

For more information, please visit the [IaC Documentation](https://oracle.github.io/ai-optimizer/advanced/iac/index.html).

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