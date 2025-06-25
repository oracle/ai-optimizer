+++
title = '💾 Settings'
weight = 40
+++

<!--
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
-->

Once you are happy with the specific configuration of your {{< short_app_ref >}}, the settings can be exported in **.json** format.  Those settings can then be loaded in later to return the {{< short_app_ref >}} to your previous configuration.  The settings an also be imported into another instance of the {{< short_app_ref >}}.

## View and Download

To view and download the {{< short_app_ref >}} configuration, navigate to `Configuration -> Settings`:

![Download Settings](../images/settings_download.png)

{{< icon "triangle-exclamation" >}} Settings contain sensitive information such as database passwords and API Keys.  By default, these settings will not be exported and will have to be re-entered after uploading the settings in a new instance of the {{< short_app_ref >}}.  If have a secure way to store the settings and would would like to export the sensitive data, tick the "Include Sensitive Settings" box.

## Upload

To upload previously downloaded settings, navigate to `Configuration -> Settings`:

![Upload Settings](../images/settings_upload.png)

1. Toggle to the "Upload" position
1. Browse files and select the settings file

If there are differences found, you can review the differences before clicking "Apply New Settings".

## SpringAI

You can download from the console a basic template that could help to expose as a OpenAI API compliant REST endpoint the RAG Chatbot defined in the chat console. 
If your configuration has both OLLAMA or OpenAI as providers for chat and embeddings LLMs, it will appear a button named “Download SpringAI”:

![SpringAI](../images/settings_spring_ai.png)

{{% notice style="code" title="No Mixing!" icon="circle-info" %}}
Currently mixed configurations, like Ollama for embeddings and OpenAI for chat completion are not allowed.
{{% /notice %}}

For more information, about the {{< short_app_ref >}} and **SpringAI**, please view the [Advanced - SpringAI](../../advanced/springai) documentation.