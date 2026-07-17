+++
title = '🤖 Model Configuration'
weight = 30
+++
<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker:ignore ollama, mxbai, nomic, thenlper, minilm, uniqueid, huggingface, hftei, openai, pplx, genai, ocid, configfile
-->

## Supported Models

At a minimum, a _Language Model_ must be configured in the {{% short_app_ref %}} for basic functionality. For Retrieval-Augmented Generation (**RAG**), an _Embedding Model_ will also need to be configured.

There is an extensive list of different model providers available to choose from.

{{% notice style="code" title="Too Small to Handle" icon="circle-info" %}}
Some older and small _Language Models_ may not have native function/tool calling support for NL2SQL and RAG, which may result in unexpected results.
{{% /notice %}}

## Configuration

The models can either be configured using environment variables or through the {{% short_app_ref %}} interface. To configure models through environment variables, please read the [Additional Information](#additional-information) about the specific model provider you would like to configure.

To configure a _Language Models_ or _Embedding Models_, from the {{% short_app_ref %}}, navigate to _Configuration_ page and _Models_ tab:

![Model Config](../images/models_config.png)

### Add/Edit/Delete

Set the Provider, API Key, and Provider URL as required.  For _Language Models_ you can also set the **Max Input Tokens (Context Length)** and **Max Output (Completion) Tokens**; for _Embedding Models_, set the **Max Chunk Size**.  These values can often be found on the model card—if they are not listed, the defaults are usually sufficient.

![Model Add/Edit](../images/models_add.png)

Most models ship pre-configured but **disabled**. When editing a model, tick the **Enabled** checkbox to activate it.

{{% notice style="code" title="More than meets the eye" icon="circle-info" %}}
Enabling a model is necessary but not always sufficient for it to appear in selection lists. The {{% short_app_ref %}} only offers models that are both enabled and reachable (a valid Provider URL, and an API Key where one is required).
{{% /notice %}}

To remove a model, use the **Delete** button while editing it; any settings that referenced it are cleared automatically.

#### Provider

The {{% short_app_ref %}} supports a number of model providers.  When adding a model, choose the most appropriate provider.  If unsure, or the specific provider is not listed, try a LiteLLM OpenAI-compatible provider, such as `openai_like` or `custom_openai`, before [opening an issue](https://github.com/oracle/ai-optimizer/issues/new) requesting additional model provider support.

There are a number of local AI Model runners that use OpenAI-compatible APIs, including:
- [LM Studio](https://lmstudio.ai)
- [vLLM](https://docs.vllm.ai/en/latest/#)
- [LocalAI](https://localai.io/)

When using these local runners, select the appropriate LiteLLM provider. For example, use `hosted_vllm` for vLLM, or an OpenAI-compatible provider such as `openai_like` or `custom_openai` for other compatible endpoints.

#### Provider URL

The Provider URL for the model will either be the *URL*, including the *IP* or *Hostname* and *Port*, of a locally running model; or the remote *URL* for a Third-Party or Cloud model.

Examples:

 - **Third-Party**: OpenAI - https://api.openai.com
 - **On-Premises**: Ollama - http://localhost:11434
 - **On-Premises**: LM Studio - http://localhost:1234/v1

#### API Keys

Third-Party cloud models, such as [OpenAI](https://openai.com/api/) and [Perplexity AI](https://docs.perplexity.ai/getting-started), require API Keys. These keys are tied to registered, funded accounts on these platforms. For more information on creating an account, funding it, and generating API Keys for third-party cloud models, please visit their respective sites.

On-Premises models, such as those from [Ollama](https://ollama.com/) or [HuggingFace](https://huggingface.co/) usually do not require API Keys. These values can be left blank.

---

## CPU Optimization

When running models on CPU-only systems (without GPU acceleration), smaller models provide significantly better performance and responsiveness. The {{% short_app_ref %}} includes built-in optimizations for CPU-friendly models.

### Recommended CPU-Friendly Models

Small local models are often a better fit for CPU-only systems. When an Ollama server is configured with `AIO_ON_PREM_OLLAMA_URL`, the {{% short_app_ref %}} discovers pulled Ollama models and enables them automatically. 

Examples of CPU-friendly model choices include:

| Model | Parameters | Max Tokens | Use Case |
|-------|-----------|------------|----------|
| `llama3.2:1b` | 1B | 2048 | Fast responses, simple Q&A |
| `granite4.1:8b` | 8B | 2048 | Balanced performance/quality |
| `gemma3:1b` | 1B | 2048 | Lightweight, efficient |

### Vector Search Optimization

When a selected model name includes a parameter count below 7B, such as `llama3.2:1b` or `gemma3:1b`, the {{% short_app_ref %}} automatically disables these Vector Search
features:

- **Store Discovery**: Uses the Language Model to select the most appropriate Vector Store. When disabled, you must select the Vector Store manually if more than one is
available.
- **Document Grading**: Evaluates retrieved documents for relevance before they are used.
- **Prompt Rephrase**: Rephrases queries using the conversation context to improve retrieval.

Disabling these features reduces the number of Language Model calls and can significantly improve response times. You can manually enable or disable each feature using the
checkboxes in the Vector Search sidebar, regardless of model size.

### Performance Tips

1. **Model Selection**: Choose the smallest model that meets your quality requirements
2. **Reduce Top K**: Lower the number of retrieved documents (e.g., Top K = 3-5)
3. **Lower Max Tokens**: Reduce maximum output tokens to speed up generation
4. **Temperature 0**: Use temperature 0 for deterministic, faster responses

---

## Additional Information

{{< tabs "uniqueid" >}}
{{% tab title="OCI GenAI" %}}

# OCI GenAI

[OCI GenAI](https://docs.oracle.com/en-us/iaas/Content/generative-ai/home.htm) is a fully managed service in Oracle Cloud Infrastructure (OCI) for seamlessly integrating versatile language models into a wide range of use cases, including writing assistance, summarization, analysis, and chat.

Please follow the [Getting Started](https://docs.oracle.com/en-us/iaas/Content/generative-ai/getting-started.htm) guide for deploying the service in your OCI tenancy.

OCI GenAI models are not added one at a time.  Instead, the {{% short_app_ref %}} loads the chat and embedding models available in your configured Region—either interactively from the [OCI](oci#interface) tab, or automatically at startup when a usable profile already has a GenAI Compartment OCID and Region persisted.  See [Loading OCI GenAI Models](oci#loading-oci-genai-models) for details.

{{% notice style="code" title="Skip the GUI!" icon="circle-info" %}}
The GenAI Compartment OCID and Region can be supplied via environment variables. See [OCI GenAI](/configuration/#oci-genai) configuration.

Alternatively, you can specify the following in the `~/.oci/config` configfile under the appropriate OCI profile:
```shell
genai_compartment_id=<OCI Compartment OCID of the OCI GenAI Service>
genai_region=<OCI GenAI Region>
```
{{% /notice %}}

{{% /tab %}}
{{% tab title="Ollama" %}}
# Ollama

[Ollama](https://ollama.com/) is an open-source project that simplifies the running of _Language Models_ and _Embedding Models_ On-Premises.

When configuring an Ollama model in the {{% short_app_ref %}}, set the `Provider URL` (e.g `http://127.0.0.1:11434`) and leave the API Key blank. Substitute the IP Address with the IP of where Ollama is running.

{{% notice style="code" title="Skip the GUI!" icon="circle-info" %}}
Ollama models can be enabled via environment variables. See [Model Overrides]({{% relref "/configuration#model-overrides" %}}) configuration.
{{% /notice %}}

## Pulling Models

You don't have to drop to the command line to make an Ollama model available. A **Pull** button appears next to any Ollama model on the _Models_ tab that hasn't been pulled to the Ollama server yet.

![Ollama Pull](../images/ollama_pull.png)

Click the "Pull" button and the {{% short_app_ref %}} downloads the model from the Ollama registry.

## Quick-start

Example of running granite4.1:8b on a Linux host:

1. Install Ollama:

```shell
sudo curl -fsSL https://ollama.com/install.sh | sh
```

1. Pull the granite4.1:8b model:

```shell
ollama pull granite4.1:8b
```

1. Start Ollama

```shell
ollama serve
```

For more information and instructions on running Ollama on other platforms, please visit the [Ollama GitHub Repository](https://github.com/ollama/ollama/blob/main/README.md#quickstart).

{{% /tab %}}
{{% tab title="HuggingFace" %}}
# HuggingFace

[HuggingFace](https://huggingface.co/) is a platform where the machine learning community collaborates on models, datasets, and applications. In the {{% short_app_ref %}}, the built-in HuggingFace embedding configuration is intended for a Hugging Face Text Embeddings Inference (TEI) endpoint.

{{% notice style="code" title="Skip the GUI!" icon="circle-info" %}}
The built-in HuggingFace TEI configuration can be enabled via environment variables. See [Model Overrides](/configuration/#model-overrides) configuration.
{{% /notice %}}

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
      --pull always $HF_IMAGE --model-id $HF_MODEL --max-client-batch-size 5024
   ```

1. Determine the IP

   ```bash
   podman inspect hftei-gte-base | grep IPA
   ```

   **NOTE:** If there is no IP, use 127.0.0.1
{{% /tab %}}
{{% tab title="Cohere" %}}
# Cohere

[Cohere](https://cohere.com/) is an AI-powered answer engine. To use Cohere, you will need to sign-up and provide the {{% short_app_ref %}} an API Key.  Cohere offers a free-trial, rate-limited API Key.

**WARNING:** Cohere is a cloud model and you should familiarize yourself with their Privacy Policies if using it to experiment with private, sensitive data in the {{% short_app_ref %}}.

{{% notice style="code" title="Skip the GUI!" icon="circle-info" %}}
Cohere models can be enabled via environment variables. See [Model Overrides]({{% relref "/configuration#model-overrides" %}}) configuration.
{{% /notice %}}
{{% /tab %}}
{{% tab title="OpenAI" %}}
# OpenAI

[OpenAI](https://openai.com/api/) is an AI research organization behind the popular, online ChatGPT chatbot. To use OpenAI models, you will need to sign-up, purchase credits, and provide the {{% short_app_ref %}} an API Key.

**WARNING:** OpenAI is a cloud model and you should familiarize yourself with their Privacy Policies if using it to experiment with private, sensitive data in the {{% short_app_ref %}}.

{{% notice style="code" title="Skip the GUI!" icon="circle-info" %}}
OpenAI models can be enabled via environment variables. See [Model Overrides]({{% relref "/configuration#model-overrides" %}}) configuration.
{{% /notice %}}

{{% /tab %}}
{{% tab title="OpenAI-Compatible" %}}
# OpenAI-Compatible

Many "AI Runners" provide OpenAI-compatible APIs. These can be configured with LiteLLM OpenAI-compatible providers such as `openai_like` or `custom_openai`. The Provider URL will normally be a local address and the API Key can often be left blank.

{{% /tab %}}
{{% tab title="Perplexity AI" %}}
# Perplexity AI

[Perplexity AI](https://docs.perplexity.ai/getting-started) is an AI-powered answer engine. To use Perplexity AI models, you will need to sign-up, purchase credits, and provide the {{% short_app_ref %}} an API Key.

**WARNING:** Perplexity AI is a cloud model and you should familiarize yourself with their Privacy Policies if using it to experiment with private, sensitive data in the {{% short_app_ref %}}.

{{% notice style="code" title="Skip the GUI!" icon="circle-info" %}}
Perplexity models can be enabled via environment variables. See [Model Overrides]({{% relref "/configuration#model-overrides" %}}) configuration.
{{% /notice %}}
{{% /tab %}}
{{< /tabs >}}
