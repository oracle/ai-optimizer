+++
title = '☁️ OCI Configuration'
weight = 30
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore genai ocid
-->

Oracle Cloud Infrastructure (OCI) can _optionally_ be configured to enable additional {{< short_app_ref >}} functionality including:

- Document Source for Splitting and Embedding from [Object Storage](https://docs.oracle.com/en-us/iaas/Content/Object/Concepts/objectstorageoverview.htm)
- Private Cloud Large Language and Embedding models from [OCI Generative AI service](https://docs.oracle.com/en-us/iaas/Content/generative-ai/home.htm)

## Configuration

OCI can either be configured through the [{{< short_app_ref >}} interface](#{{< short_app_ref >}}-interface), a [CLI Configuration File](#config-file), or by using [environment variables](#environment-variables).

You will need to [generate an API Key](https://docs.oracle.com/en-us/iaas/Content/API/Concepts/apisigningkey.htm#two) to obtain the required configuration values.

---

### Interface

To configure the Database from the {{< short_app_ref >}}, navigate to _Configuration_ menu and _OCI_ tab:

![OCI Config](../images/oci_config.png)

Provide the values obtained by [generating an API Key](https://docs.oracle.com/en-us/iaas/Content/API/Concepts/apisigningkey.htm#two).

OCI GenAI Services can also be configured on this page, once OCI access has been confirmed.



---

### Config File

Depending on the runtime environment, either [Bare Metal](#bare-metal) or [Containerized](#container), your local [CLI Configuration File](https://docs.oracle.com/en-us/iaas/Content/API/Concepts/sdkconfig.htm) can be used to configure {{< short_app_ref >}} for OCI access.

In addition to the standard configuration file, two additional entries are required to enable OCI GenAI Services:

- **genai_region**: the Region for the OCI GenAI Service
- **genai_compartment_id**: the Compartment OCID of the OCI GenAI Service

#### Bare Metal

During startup, the {{< short_app_ref >}} will automatically look for and consume a [CLI Configuration File](https://docs.oracle.com/en-us/iaas/Content/API/Concepts/sdkconfig.htm) for configuring OCI access.

#### Container

When starting the container, volume mount the configuration file to `/app/.oci` for it to be used.  

For example:
```bash
podman run -v ~/.oci:/app/.oci -p 8501:8501 -it --rm ai-optimizer-aio
```

---

### Environment Variables

The {{< short_app_ref >}} can use environment variables to configure OCI.  Environment variables **will take precedence over the CLI Configuration file**.

In addition to the [standard environment variables](https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/clienvironmentvariables.htm#CLI_Environment_Variables), the following variables can be set to enable OCI GenAI Services:

- **OCI_GENAI_SERVICE_ENDPOINT**: the URL endpoint for the OCI GenAI Service
- **OCI_GENAI_COMPARTMENT_ID**: the compartment OCID of the OCI GenAI Service

You can also configure OCI using environment variables when running in a container. However, this approach can be tedious, as it requires specifying the contents of the API key directly, rather than referencing a file.

For example:
```bash
podman run \
 -e OCI_CLI_USER=<user_ocid> \
 -e OCI_CLI_KEY_CONTENT=<api key> \
 -p 8501:8501 -it --rm ai-optimizer-aio
```