+++
title = " "
menus = 'main'
archetype = "home"
description = './ai-optimizer/docs'
keywords = 'oracle optimizer toolkit microservices development genai rag'
+++

<!--
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker:ignore streamlit, genai, venv
-->

The {{< full_app_ref >}} provides a streamlined environment where developers and data scientists can explore the potential of Generative Artificial Intelligence (**GenAI**) combined with Retrieval-Augmented Generation (**RAG**) capabilities. By integrating Oracle Database AI VectorSearch and SelectAI, the {{< short_app_ref >}} enables users to enhance existing Large Language Models (**LLM**s) through **RAG**. This method significantly improves the performance and accuracy of AI models, helping to avoid common issues such as knowledge cutoff and hallucinations.

- **GenAI**: Powers the generation of text, images, or other data based on prompts using pre-trained **LLM**s.
- **RAG**: Enhances **LLM**s by retrieving relevant, real-time information allowing models to provide up-to-date and accurate responses.
- **Vector Database**: A database, including Oracle AI Database, that can natively store and manage vector embeddings and handle the unstructured data they describe, such as documents, images, video, or audio.

## Features

- [Configuring Embedding and Chat Models](client/configuration/model_config)
- [Splitting and Embedding Documentation](client/tools/split_embed)
- [Modifying System Prompts (Prompt Engineering)](client/tools/prompt_eng)
- [Experimenting with **LLM** Parameters](client/chatbot)
- [Testbed for auto-generated or existing Q&A datasets](client/testbed)

The {{< short_app_ref >}} streamlines the entire workflow from prototyping to production, making it easier to create and deploy RAG-powered GenAI solutions using the **Oracle Database**.

# Getting Started

The {{< short_app_ref >}} is available to install in your own environment, which may be a developer's desktop, on-premises data center environment, or a cloud provider. It can be run either on bare-metal, within a container, or in a Kubernetes Cluster.

{{% notice style="code" title="Prefer a Step-by-Step?" icon="circle-info" %}}
<!-- Hard-coding AI Optimizer to avoid unsafe HTML, this is an exception -->
The [Walkthrough](walkthrough) is a great way to familiarize yourself with the **AI Optimizer** and its features in a development environment.
{{% /notice %}}

## Prerequisites

- Oracle AI Database incl. Oracle AI Database Free
- Python 3.11 (for running Bare-Metal)
- Container Runtime e.g. docker/podman (for running in a Container)
- Access to an Embedding and Chat Model:
  - API Keys for Third-Party Models
  - On-Premises Models*

~\*Oracle recommends running On-Premises Models on hardware with GPUs. For more information, please review the [{{< short_app_ref >}}](client/) documentation.~

### Bare-Metal Installation

To run the application on bare-metal, download the latest release:
{{< latest_release >}}

1. Uncompress the release in a new directory.  For example:

   ```bash
   mkdir ai-optimizer
   tar zxf ai-optimizer-src.tar.gz -C ai-optimizer

   cd ai-optimizer
   ```

1. Create and activate a Python Virtual Environment:

   ```bash
   cd ai-optimizer
   python3.11 -m venv .venv
   source .venv/bin/activate
   pip3.11 install --upgrade pip wheel uv
   ```

1. Install the Python modules:

   ```bash
   uv pip install -e ".[all]"
   ```

1. Start Streamlit:

   ```bash
   streamlit run launch_client.py --server.port 8501
   ```

1. Navigate to `http://localhost:8501`.

1. [Configure](client/configuration) the {{< short_app_ref >}}.

### Container Installation

{{% notice style="code" title="Same... but Different" icon="circle-info" %}}
References to `podman` commands, if applicable to your environment, can be substituted with `docker`.
{{% /notice %}}

To run the application in a container, download the latest release:
{{< latest_release >}}

1. Uncompress the release in a new directory.  For example:

   ```bash
   mkdir ai-optimizer
   tar zxf ai-optimizer-src.tar.gz -C ai-optimizer

   cd ai-optimizer
   ```

1. Build the *ai-optimizer-aio* image.

   _Note:_ MacOS Silicon users may need to specify `--arch amd64`

   ```bash
   podman build -f src/Dockerfile -t ai-optimizer-aio .
   ```

1. Start the Container:

   ```bash
   podman run -p 8501:8501 -it --rm ai-optimizer-aio
   ```

1. Navigate to `http://localhost:8501`.

1. [Configure](client/configuration) the {{< short_app_ref >}}.

### Advanced Installation

The {{< short_app_ref >}} is designed to operate within a Microservices Architecture, leveraging Microservices Infrastructure like Kubernetes.
Review [{{< short_app_ref >}}](client) components and the additional [Oracle Kubernetes Engine](advanced/iac/#oracle-kubernetes-engine) documentation for more information.
