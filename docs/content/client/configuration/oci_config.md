+++
title = '☁️ OCI Configuration'
weight = 30
+++

<!--
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore genai ocid
-->

Oracle Cloud Infrastructure (OCI) can _optionally_ be configured to enable additional {{< short_app_ref >}} functionality including:

- Document Source for Splitting and Embedding from [Object Storage](https://docs.oracle.com/en-us/iaas/Content/Object/Concepts/objectstorageoverview.htm)
- Private Cloud Large Language and Embedding models from [OCI Generative AI service](https://docs.oracle.com/en-us/iaas/Content/generative-ai/home.htm)

## Configuration

OCI can either be configured through the [{{< short_app_ref >}} interface](#{{< short_app_ref >}}-interface), a [CLI Configuration File](#config-file), or by using [environment variables](#environment-variables).  
You will need to [generate an API Key](https://docs.oracle.com/en-us/iaas/Content/API/Concepts/apisigningkey.htm#two) to obtain the required configuration values.

### {{< short_app_ref >}} Interface

To configure the Database from the {{< short_app_ref >}}, navigate to `Configuration -> OCI`:

![OCI Config](../images/oci_config.png)

OCI GenAI Services can be configured once OCI access has been confirmed:

![OCI GenAI Config](../images/oci_genai_config.png)

Provide the values obtained by [generating an API Key](https://docs.oracle.com/en-us/iaas/Content/API/Concepts/apisigningkey.htm#two).

### Config File

During startup, the {{< short_app_ref >}} will look for and consume a [CLI Configuration File](https://docs.oracle.com/en-us/iaas/Content/API/Concepts/sdkconfig.htm) for configuring OCI access.

In addition to the standard entries, two additional entries are required to enable OCI GenAI Services:

- **service_endpoint**: the URL endpoint for the OCI GenAI Service
- **compartment_id**: the compartment OCID of the OCI GenAI Service


### Environment Variables

During start, the {{< short_app_ref >}} will use environment variables to configure OCI.  Environment variables will take precedence over the CLI Configuration file.

In addition to the [standard environment variables](https://docs.oracle.com/en-us/iaas/Content/API/SDKDocs/clienvironmentvariables.htm#CLI_Environment_Variables), the following variables can be set to enable OCI GenAI Services:

- **OCI_GENAI_SERVICE_ENDPOINT**: the URL endpoint for the OCI GenAI Service
- **OCI_GENAI_COMPARTMENT_ID**: the compartment OCID of the OCI GenAI Service
