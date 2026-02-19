+++
title = '💾 Settings'
weight = 40
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
-->

Once you are happy with the specific configuration of your {{< short_app_ref >}}, the settings can be exported in **.json** format.  Those settings can then be loaded in later to return the {{< short_app_ref >}} to your previous configuration.  The settings can also be imported into another instance of the {{< short_app_ref >}}.

## View and Download

To view and download the {{< short_app_ref >}} configuration, navigate to the _Configuration_ page and _Settings_ tab:

![Download Settings](../images/settings_download.png)

{{< icon "triangle-exclamation" >}} Settings contain sensitive information such as database passwords and API Keys.  By default, these settings will not be exported and will have to be re-entered after uploading the settings in a new instance of the {{< short_app_ref >}}.  If you have a secure way to store the settings and would like to export the sensitive data, tick the "Include Sensitive Settings" box.

## Upload

To upload previously downloaded settings, navigate to `Configuration -> Settings`:

![Upload Settings](../images/settings_upload.png)

1. Toggle to the "Upload" button
1. Browse files and select the settings file

If differences are found, you can review the differences before clicking "Apply New Settings".

## Source Code Templates

You can download basic templates from the console to help expose the RAG chatbot defined in the chat console as an OpenAI API–compatible REST endpoint.

If your configuration includes either Ollama or OpenAI as providers for both chat and embedding models, the *Download LangChain MCP* and *Download Spring AI* buttons will be displayed.

![SpringAI](../images/settings_spring_ai.png)

{{% notice style="code" title="No Mixing!" icon="circle-info" %}}
Mixed configurations, like Ollama for embeddings and OpenAI for chat completion are not currently allowed.
{{% /notice %}}

For more information, about the {{< short_app_ref >}} and  downloadable templates:

* **LangchainMCP**: please view the [Advanced - Export as Langchain server](../../advanced/langchain_mcp.md) documentation.
* **SpringAI**: please view the [Advanced - SpringAI](../../advanced/springai) documentation.
