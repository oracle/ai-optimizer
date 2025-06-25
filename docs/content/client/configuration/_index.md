+++
title = 'Configuration'
menus = 'main'
weight = 100
+++

<!--
Copyright (c) 2024, 2025, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
-->

The {{< full_app_ref >}} is not configured out-of-the-box. To enable functionality, an embedding model, language model, database, and optionally, Oracle Cloud Infrastructure (OCI) will need to be configured.

Once you have configured the {{< short_app_ref >}}, the settings can be exported to be imported into another deployment or after a restart.

## 🤖 Model Configuration

At a minimum, a large language model (LLM) will need to be configured to experiment with the {{< short_app_ref >}}. The LLM can be a third-party LLM, such as ChatGPT or Perplexity, or an on-premises LLM.

Additionally, to enable Retrieval-Augmented Generation (RAG) capabilities, an embedding model will need to be configured and enabled.

For more information on the currently supported models and how to configure them, please read about [Model Configuration](model_config/).

{{< icon "star" >}} _If you are experimenting with sensitive, private data_, it is recommended to run both the embedding and LLM on-premises.

## 🗄️ Database Configuration

A 23ai Oracle Database is required to store the embedding vectors to enable Retrieval-Augmented Generation (RAG). The ChatBot can be used without a configured database, but you will be unable to split/embed or experiment with RAG in the ChatBot.

For more information on configuring the database, please read about [Database Configuration](db_config/).

## ☁️ OCI Configuration (Optional)

Oracle Cloud Infrastructure (OCI) Object Storage buckets can be used to store documents for embedding and to store the split documents before inserting them in the Oracle Database Vector Store.

Additionally, OCI GenAI services can be used for both private-cloud based LLM and Embedding Models.

For more information on configuring OCI, please read about [OCI Configuration](oci_config/).

## 💾 Settings

Once you have configured the {{< short_app_ref >}}, you can export the settings and import them after a restart or new deployment.

For more information on importing (and exporting) settings, please read about [Settings](settings/).
