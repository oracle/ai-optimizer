+++
title = '🔒 Deep Data Security'
weight = 30
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore relref deepsec nl2sql
-->

Oracle Deep Data Security enforces fine-grained, identity-aware authorization directly in the database. You define declarative policies, **data grants**, that control access at the row and column level for **data roles** and **end users**. Because the policies are enforced inside the database, they apply to every access path, including the AI Optimizer's [Natural Language to SQL]({{% relref "/client/chatbot" %}}) agent: once a data grant is in place, the agent's queries see exactly the data the policy allows.

The Deep Data Security tool lets you create and manage these objects from the AI Optimizer.

{{% notice style="default" title="Requires Oracle AI Database 26ai" icon="circle-info" %}}
Deep Data Security is available in Oracle AI Database 26ai. When the connected database does not support it, the **Deep Data Security** tab detects this and is automatically disabled.
{{% /notice %}}

## Prerequisites

The configured database user needs the Deep Data Security privileges described in the [Database Configuration]({{% relref "/client/configuration/databases" %}}) documentation. The tool reads the user's privileges and enables only the actions that are permitted; anything the user is not privileged to do is disabled.

## Using the tool

Open the **Tools** menu and select the **Deep Data Security** tab. It is organized into three sections:

### Data Roles

Create and drop **data roles**, the principals that data grants authorize. A data role can be local, or mapped to an external application role (for example, an identity-provider group).

### End Users

Create and drop Deep Data Security **end users**, the identities whose access is governed by data grants.

Use **Connect tools as** to make Vector Search and NL2SQL connect as a selected end user for the active database. This lets you preview how those tools behave for a governed identity while keeping the AI Optimizer configuration connected as the database user that manages the objects.

### Data Grants

Build a **data grant** that authorizes a data role against one of your tables or views:

- Choose the **object** (table or view) and one or more **privileges** (`SELECT`, `INSERT`, `UPDATE`, `DELETE`).
- Restrict access to **specific columns**, or to **all columns except** a chosen set, for column-level control.
- Add an optional **row predicate** (a SQL `WHERE` expression) for row-level control.
- Select the **data role** to grant to.

The generated `CREATE DATA GRANT` statement is shown for review before you apply it. Existing data grants are listed and can be dropped.
