+++
title = " "
menus = 'main'
archetype = "home"
description = './ai-optimizer/docs'
keywords = 'oracle optimizer toolkit microservices development genai rag'
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker:ignore streamlit genai relref venv
-->

The {{% full_app_ref %}} provides a streamlined environment where developers and data scientists can explore the potential of Generative Artificial Intelligence (**GenAI**) combined with Retrieval-Augmented Generation (**RAG**) capabilities. By integrating Oracle Database AI VectorSearch and SQLcl MCP, the {{% short_app_ref %}} enables users to enhance existing Large Language Models (**LLM**s) through **RAG** and Natural Language to SQL (**NL2SQL**). This method significantly improves the performance and accuracy of AI models, helping to avoid common issues such as knowledge cutoff and hallucinations.

- **GenAI**: Powers the generation of text, images, or other data based on prompts using pre-trained **LLM**s.
- **RAG**: Augments **LLM**s knowledge by retrieving relevant, unstructured data.
- **NL2SQL**: Enhances **LLM**s by retrieving relevant, real-time structured data allowing models to provide up-to-date and accurate responses.
- **Vector Database**: A database, including Oracle AI Database, that can natively store and manage vector embeddings and handle the unstructured data they describe, such as documents, images, video, or audio.

## Features

- [Configuring Embedding and Chat Models]({{% relref "/client/configuration/models" %}})
- [Splitting and Embedding Documentation]({{% relref "/client/tools/split_embed" %}})
- [Modifying System Prompts (Prompt Engineering)]({{% relref "/client/tools/prompt_eng" %}})
- [Experimenting with **LLM** Parameters]({{% relref "/client/chatbot" %}})
- [Testbed for auto-generated or existing Q&A datasets]({{% relref "/client/testbed" %}})

The {{% short_app_ref %}} streamlines the entire workflow from prototyping to production, making it easier to create and deploy RAG-powered GenAI solutions using the **Oracle Database**.

# Getting Started

The {{% short_app_ref %}} is available to install in your own environment, which may be a developer's desktop, on-premises data center environment, or a cloud provider. It can be run either on bare-metal, within a container, or in a Kubernetes Cluster.

{{% notice style="code" title="Prefer a Step-by-Step?" icon="circle-info" %}}
<!-- Hard-coding AI Optimizer to avoid raw HTML, this is an exception -->
The [Walkthrough]({{% relref "/walkthrough" %}}) is a great way to familiarize yourself with the **AI Optimizer** and its features in a development environment.
{{% /notice %}}

## Prerequisites

- Python 3.11 (for running Bare-Metal)
- Container Runtime e.g. docker/podman (for running in a Container)
- Access to an Embedding and Chat Model:
  - API Keys for Third-Party Models
  - On-Premises Models*
- Oracle AI Database incl. Oracle AI Database Free (for RAG and persisting settings)

~\*Oracle recommends running On-Premises Models on hardware with GPUs. For more information, please review the [{{% short_app_ref %}}]({{% relref "/client" %}}) documentation.~

{{% notice style="code" title="What do I actually need?" icon="circle-info" %}}
<!-- Hard-coding AI Optimizer to avoid raw HTML, this is an exception -->
The **AI Optimizer** will start and allow interaction with language models without any database or pre-configuration. However, to persist settings across restarts and to enable features like RAG, NL2SQL and the [Testbed]({{% relref "/client/testbed" %}}), at a minimum a [database]({{% relref "/client/configuration/databases" %}}) should be configured.
{{% /notice %}}

### Bare-Metal Installation

To run the application on bare-metal, download the latest release:
{{% latest_release %}}

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

1. _(Optional)_ Create an [environment file]({{% relref "/env_config" %}}) to pre-configure the application:

   ```bash
   cp src/.env.example src/.env.dev
   ```

   Edit `src/.env.dev` as needed. See [Environment Configuration]({{% relref "/env_config" %}}) for details.

1. Start the application:

   ```bash
   python src/entrypoint.py client
   ```

1. Navigate to `http://localhost:8501`.

1. [Configure]({{% relref "/client/configuration" %}}) the {{% short_app_ref %}}.

### Container Installation

{{< podman_note >}}

To run the application in a container, download the latest release:
{{% latest_release %}}

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

1. [Configure]({{% relref "/client/configuration" %}}) the {{% short_app_ref %}}.

### Advanced Installation

The {{% short_app_ref %}} is designed to operate within a Microservices Architecture, leveraging Microservices Infrastructure like Kubernetes.
Review [{{% short_app_ref %}}]({{% relref "/client" %}}) components and the additional [Oracle Kubernetes Engine]({{% relref "/advanced/iac#oracle-kubernetes-engine" %}}) documentation for more information.
