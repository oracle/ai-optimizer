+++
title = '☁️ OCI Configuration'
weight = 40
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore genai ocid
-->

Oracle Cloud Infrastructure (OCI) can _optionally_ be configured to enable additional {{% short_app_ref %}} functionality including:

- Document Source for Splitting and Embedding from [Object Storage](https://docs.oracle.com/en-us/iaas/Content/Object/Concepts/objectstorageoverview.htm)
- Private Cloud Large Language and Embedding models from [OCI Generative AI service](https://docs.oracle.com/en-us/iaas/Content/generative-ai/home.htm)

## Configuration

OCI can either be configured through the {{% short_app_ref %}} [interface](#interface), a [CLI Configuration File](#config-file), or by using [environment variables](#environment-variables).

You will need to [generate an API Key](https://docs.oracle.com/en-us/iaas/Content/API/Concepts/apisigningkey.htm#two) to obtain the required configuration values.

---

### Interface

To configure OCI access from the {{% short_app_ref %}}, navigate to _Configuration_ menu and _OCI_ tab:

![OCI Config](../images/oci_config.png)

Provide the values obtained by [generating an API Key](https://docs.oracle.com/en-us/iaas/Content/API/Concepts/apisigningkey.htm#two).

OCI GenAI Services can also be configured on this page, once OCI access has been confirmed.

---

### Config File

Depending on the runtime environment, either [Bare Metal](#bare-metal) or [Containerized](#container), your local [CLI Configuration File](https://docs.oracle.com/en-us/iaas/Content/API/Concepts/sdkconfig.htm) can be used to configure {{% short_app_ref %}} for OCI access.

In addition to the standard configuration file entries, two additional entries can be added to enable OCI GenAI Services:

- **genai_region**: the Region for the OCI GenAI Service
- **genai_compartment_id**: the Compartment OCID of the OCI GenAI Service

#### Bare Metal

During startup, the {{% short_app_ref %}} will automatically look for and consume a [CLI Configuration File](https://docs.oracle.com/en-us/iaas/Content/API/Concepts/sdkconfig.htm) for configuring OCI access.

#### Container

When starting the container, volume mount the configuration file to `/app/.oci` for it to be used.

For example:
```bash
podman run -v ~/.oci:/app/.oci -p 8501:8501 -it --rm ai-optimizer-aio
```

---

### Environment Variables

OCI can also be configured using environment variables. See the [OCI CLI Overrides](/env_config/#oci-cli-overrides) and [OCI GenAI](/env_config/#oci-genai) sections of the Configuration page for available variables and usage.

---

### Authentication Types

The following authentication types are supported via the `AIO_OCI_CLI_AUTH` variable or the `authentication` field in the config file:

| Value | Description | Use Case |
|---|---|---|
| `api_key` | API key with user, fingerprint, tenancy, and private key | Default; local development and service accounts |
| `instance_principal` | Instance Principals security token | OCI compute instances with dynamic group policies |
| `resource_principal` | Resource Principals signer | OCI Functions and other resource-principal-enabled services |
| `oke_workload_identity` | OKE workload identity resource principal | Pods running on Oracle Kubernetes Engine |
| `security_token` | Security token from file with private key | OCI Cloud Shell and token-based authentication |
