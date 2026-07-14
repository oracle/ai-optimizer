+++
title = 'Use Cases'
menus = 'main'
weight = 12
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore NL2SQL relref
-->

Use cases are end-to-end demos that show the {{% short_app_ref %}} working on a complete, realistic scenario. They pick up where the [Walkthrough]({{% relref "/walkthrough" %}}) leaves off.

Once you have:

- a chat model;
- an embedding model; and
- an Oracle AI Database configured,

a use-case takes you from an ungrounded **Language Model** to one grounded in your own structured data (**NL2SQL**) and unstructured documents (**Vector Search**).

Each use-case is self-contained; it lists the data and prompts it needs, the models it was tuned against, and example questions to ask at each step. However, you are encouraged to experiment with different models, different prompts, and a variety of questions.

{{% notice style="code" title="New here?" icon="circle-info" %}}
If you haven't set up the {{% short_app_ref %}} yet, start with the [Walkthrough]({{% relref "/walkthrough" %}}). It installs a local environment you can reuse.
{{% /notice %}}

## Available Use Cases

{{% children description="true" %}}
