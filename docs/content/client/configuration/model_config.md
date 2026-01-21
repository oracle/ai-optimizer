+++
title = '🤖 Model Configuration'
weight = 10
+++
<!--
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker:ignore ollama, mxbai, nomic, thenlper, minilm, uniqueid, huggingface, hftei, openai, pplx, genai, ocid, configfile
-->

## Supported Models

At a minimum, a Large _Language Model_ (LLM) must be configured in {{< short_app_ref >}} for basic functionality. For Retrieval-Augmented Generation (**RAG**), an _Embedding Model_ will also need to be configured.

There is an extensive list of different API Model APIs available you can choose from.

{{% notice style="code" title="Compatibility notice" icon="fire" %}}
To use **NL2SQL**, the selected LLM must support the **Model Context Protocol (MCP)**. LLM runtimes without native MCP support—such as the Ollama desktop application and core server—cannot fully enable these features.
{{% /notice %}}

## Configuration

The models can either be configured using environment variables or through the {{< short_app_ref >}} interface. To configure models through environment variables, please read the [Additional Information](#additional-information) about the specific model you would like to configure.

To configure an LLM or embedding model from the {{< short_app_ref >}}, navigate to _Configuration_ page and _Models_ tab:

![Model Config](../images/models_config.png)

Here you can add and/or configure both Large _Language Models_ and _Embedding Models_. 

### Add/Edit

Set the API, API Keys, API URL and other parameters as required.  Parameters such as Default Temperature, Context Length, and Penalties can often be found on the model card.  If they are not listed, the defaults are usually sufficient.

![Model Add/Edit](../images/models_add.png)

#### API

The {{< short_app_ref >}} supports a number of model API's.  When adding a model, choose the most appropriate Model API.  If unsure, or the specific API is not listed, try *CompatOpenAI* or *CompatOpenAIEmbeddings* before [opening an issue](https://github.com/oracle/ai-optimizer/issues/new) requesting an additional model API support.

There are a number of local AI Model runners that use OpenAI compatible API's, including:
- [LM Studio](https://lmstudio.ai)
- [vLLM](https://docs.vllm.ai/en/latest/#)
- [LocalAI](https://localai.io/)

When using these local runners, select the appropriate compatible OpenAI API (Language: **CompatOpenAI**; Embeddings: **CompatOpenAIEmbeddings**).

#### API URL

The API URL for the model will either be the *URL*, including the *IP* or *Hostname* and *Port*, of a locally running model; or the remote *URL* for a Third-Party or Cloud model.

Examples:
 - **Third-Party**: OpenAI - https://api.openai.com
 - **On-Premises**: Ollama - http://localhost:11434
 - **On-Premises**: LM Studio - http://localhost:1234/v1

#### API Keys

Third-Party cloud models, such as [OpenAI](https://openai.com/api/) and [Perplexity AI](https://docs.perplexity.ai/getting-started), require API Keys. These keys are tied to registered, funded accounts on these platforms. For more information on creating an account, funding it, and generating API Keys for third-party cloud models, please visit their respective sites.

On-Premises models, such as those from [Ollama](https://ollama.com/) or [HuggingFace](https://huggingface.co/) usually do not require API Keys. These values can be left blank.


## Additional Information

{{< tabs "uniqueid" >}}
{{% tab title="OCI GenAI" %}}
# OCI GenAI

[OCI GenAI](https://docs.oracle.com/en-us/iaas/Content/generative-ai/home.htm) is a fully managed service in Oracle Cloud Infrastructure (OCI) for seamlessly integrating versatile language models into a wide range of use cases, including writing assistance, summarization, analysis, and chat.

Please follow the [Getting Started](https://docs.oracle.com/en-us/iaas/Content/generative-ai/getting-started.htm) guide for deploying the service in your OCI tenancy.

To use OCI GenAI, the {{< short_app_ref >}} must be configured for [OCI access](oci_config); including the Compartment OCID for the OCI GenAI service.

>[!code]Skip the GUI!
>You can set the following environment variables to automatically enable OCI GenAI models:
>```shell
>export OCI_GENAI_REGION=<OCI GenAI Service Region>
>export OCI_GENAI_COMPARTMENT_ID=<OCI Compartment OCID of the OCI GenAI Service>
>```
>
>Alternatively, you can specify the following in the `~/.oci/config` configfile under the appropriate OCI profile:
>```shell
>genai_compartment_id=<OCI Compartment OCID of the OCI GenAI Service>
>genai_region=<OCI GenAI Region>
>```

{{% /tab %}}
{{% tab title="Ollama" %}}
# Ollama

[Ollama](https://ollama.com/) is an open-source project that simplifies the running of LLMs and Embedding Models On-Premises.

When configuring an Ollama model in the {{< short_app_ref >}}, set the `API Server` URL (e.g `http://127.0.0.1:11434`) and leave the API Key blank. Substitute the IP Address with the IP of where Ollama is running.

>[!code]Skip the GUI!
>You can set the following environment variable to automatically set the `API Server` URL and enable Ollama models (change the IP address and Port, as applicable to your environment):
>```shell
>export ON_PREM_OLLAMA_URL=http://127.0.0.1:11434
>```

## Quick-start

Example of running llama3.1 on a Linux host:

1. Install Ollama:

```shell
sudo curl -fsSL https://ollama.com/install.sh | sh
```

1. Pull the llama3.1 model:

```shell
ollama pull llama3.1
```

1. Start Ollama

```shell
ollama serve
```

For more information and instructions on running Ollama on other platforms, please visit the [Ollama GitHub Repository](https://github.com/ollama/ollama/blob/main/README.md#quickstart).

{{% /tab %}}
{{% tab title="HuggingFace" %}}
# HuggingFace

[HuggingFace](https://huggingface.co/) is a platform where the machine learning community collaborates on models, datasets, and applications. It provides a large selection of models that can be run both in the cloud and On-Premises.

>[!code]Skip the GUI!
>You can set the following environment variable to automatically set the `API Server` URL and enable HuggingFace models (change the IP address and Port, as applicable to your environment):
:
>```shell
>export ON_PREM_HF_URL=http://127.0.0.1:8080
>```

## Quick-start

Example of running thenlper/gte-base in a container:

1. Set the Model based on CPU or GPU

   - For CPUs: `export HF_IMAGE=ghcr.io/huggingface/text-embeddings-inference:cpu-1.2`
   - For GPUs: `export HF_IMAGE=ghcr.io/huggingface/text-embeddings-inference:0.6`

1. Define a Temporary Volume

   ```bash
   export TMP_VOLUME=/tmp/hf_data
   mkdir -p $TMP_VOLUME
   ```

1. Define the Model

   ```bash
   export HF_MODEL=thenlper/gte-base
   ```

1. Start the Container

   ```bash
   podman run -d -p 8080:80 -v $TMP_VOLUME:/data --name hftei-gte-base \
       --pull always ${image} --model-id $HF_MODEL --max-client-batch-size 5024
   ```

1. Determine the IP

   ```bash
   docker inspect hftei-gte-base | grep IPA
   ```

   **NOTE:** If there is no IP, use 127.0.0.1
{{% /tab %}}
{{% tab title="Cohere" %}}
# Cohere

[Cohere](https://cohere.com/) is an AI-powered answer engine. To use Cohere, you will need to sign-up and provide the {{< short_app_ref >}} an API Key.  Cohere offers a free-trial, rate-limited API Key.

**WARNING:** Cohere is a cloud model and you should familiarize yourself with their Privacy Policies if using it to experiment with private, sensitive data in the {{< short_app_ref >}}.

>[!code]Skip the GUI!
>You can set the following environment variable to automatically set the `API Key` and enable Perplexity models:
:
>```shell
>export COHERE_API_KEY=<super-secret API Key>
>```
{{% /tab %}}
{{% tab title="OpenAI" %}}
# OpenAI

[OpenAI](https://openai.com/api/) is an AI research organization behind the popular, online ChatGPT chatbot. To use OpenAI models, you will need to sign-up, purchase credits, and provide the {{< short_app_ref >}} an API Key.

**WARNING:** OpenAI is a cloud model and you should familiarize yourself with their Privacy Policies if using it to experiment with private, sensitive data in the {{< short_app_ref >}}.

>[!code]Skip the GUI!
>You can set the following environment variable to automatically set the `API Key` and enable OpenAI models:
:
>```shell
>export OPENAI_API_KEY=<super-secret API Key>
>```

{{% /tab %}}
{{% tab title="CompatOpenAI" %}}
# Compatible OpenAI

Many "AI Runners" provide OpenAI compatible APIs.  These can be used without any specific API by using the **Compat**OpenAI API specification.  The API URL will normally be a local address and the API Key can be left blank.

{{% /tab %}}
{{% tab title="Perplexity AI" %}}
# Perplexity AI

[Perplexity AI](https://docs.perplexity.ai/getting-started) is an AI-powered answer engine. To use Perplexity AI models, you will need to sign-up, purchase credits, and provide the {{< short_app_ref >}} an API Key.

**WARNING:** Perplexity AI is a cloud model and you should familiarize yourself with their Privacy Policies if using it to experiment with private, sensitive data in the {{< short_app_ref >}}.

>[!code]Skip the GUI!
>You can set the following environment variable to automatically set the `API Key` and enable Perplexity models:
:
>```shell
>export PPLX_API_KEY=<super-secret API Key>
>```
{{% /tab %}}
{{< /tabs >}}
