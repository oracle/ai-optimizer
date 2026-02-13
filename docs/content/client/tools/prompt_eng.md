+++
title = '🎤 Prompts'
weight = 10
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
-->

Prompts are a set of instructions given to the language model to guide the response.  They are used to set the context or define the kind of response you are expecting.  The {{< full_app_ref >}} provides both [System](#system-prompt) and [Context](#context-prompt) example prompts and allows you to modify these prompts to your needs.

{{% icon star %}} The provided example prompts work for *most* models but they may not work the same way across all models.  Different models may interpret or respond to the instructions in various ways requiring you to modify the example prompts per-model.

The select "Current" prompt is what will be used while interacting with the language model and will be displayed within the [ChatBot](../chatbot) input bar:

![Chatbot Input](../images/chatbot_input_bar.png)

## System Prompt

The *System* prompt is typically used to guide the model on how to interpret input, what style or tone to use, or what kind of response is expected. *System* prompts help establish the parameters within which the language model operates, shaping its output beyond just answering direct user queries.  

The *System* prompt for non-RAG and RAG will normally provide different instructions to the model to guide its use of the retrieved documents.  You can select which prompt to use and modify the provided examples as required.

![System Prompt](../images/prompt_eng_system.png)

{{% notice style="code" title="Auto Switcher-oo" icon="circle-info" %}}
When enabling or disabling Vector Search, the *System* prompt will automatically switch between the **Basic Example** and **Vector Search Example**.  When the *System* prompt has been set to **Custom**, this auto-switching will be disabled.
{{% /notice %}}

#### Examples of how the *System* prompt can be used:

##### Set the Tone/Style

- Respond in a formal tone,
- Respond as if you were a pirate.
- Be friendly and casual in your answers.

##### Influence the behavior/role

- Act like a professional teacher
- Pretend you are a counselor helping someone with stress

##### Guide the context

- Only provide technical details about the topic
- Explain this concept as if the user is a beginner

##### Specify the output format

- Give answers in bullet-point lists
- Restrict your response to three sentences or less

---
## Context Prompt

The *Context* prompt is used when Vector Search is enabled.  It is used in a "private conversation" with the model, prior to retrieval, to re-phrase the user input.  

![Context Prompt](../images/prompt_eng_context.png)

As an example to the importance of the *Context* prompt, if the previous interactions with the model included Oracle documentation topics about vector indexes and the user asks: "Can you give me more details?"; the Vector Search retrieval process should not search for similar vectors for "Can you give me more details?".  Instead, the user input should be re-phrased and a vector search should be performed on a more contextual relevant phrase, such as: "More details on creating and altering hybrid vector indexes in Oracle Database."

When Vector Search is enabled, you will see what was generated and used for the vector search in the **Notes:** section under the **References:**

![System Prompt](../images/chatbot_rephrase.png)