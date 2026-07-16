+++
title = '🎤 Prompts'
weight = 10
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.
-->

Prompts are a set of instructions given to the language model to guide the response.  They are used to set the context or define the kind of response you are expecting.  The {{% full_app_ref %}} provides a number of example prompts which are automatically used based on the features enabled.

{{% icon star %}} The provided example prompts work for *most* models but they may not work the same way across all models.  Different models may interpret or respond to the instructions in various ways requiring you to modify the example prompts per-model.

## System Prompts

System Prompts are used to guide the model on how to interpret input, what style or tone to use, or what kind of response is expected. They help establish the parameters within which the language model operates, shaping its output beyond just answering direct user queries.  

The {{% short_app_ref %}} will automatically switch prompts based on the tools and options selected.  For example, when *Vector Search* is enabled, the _Vector Search Tools Prompt_ will provide the overall model guideance.  When specific *Vector Search* options are enabled, other prompts will guide those specific options:
 - Store Discover: _Smart Vector Storage Prompt_
 - Prompt Rephrase: _Contextualize Prompt_ & _Vector Search Rephrase Prompt_
 - Document Grading: _Vector Search Grading Prompt_

![System Prompts](../images/prompt_eng_system.png)

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

