+++
title = 'Collaboration & Multi-User'
weight = 25
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore streamlit nl2sql hmac langgraph
-->

A single {{% short_app_ref %}} API Server can serve many clients at once — multiple people using the GUI, several IDE or MCP sessions, and external applications.  This page explains how those clients are kept apart, which configuration they share, and how to protect shared configuration with a password.

## Client IDs

Every request to the API Server carries a **client ID** that identifies the session it belongs to.  The server keeps a separate set of settings and conversation history for each distinct ID.

- The **{{% short_app_ref %}} GUI client** generates a fresh, random ID (a UUID) for each browser session.  You can see the current value under **☰ → About** in the GUI.
- **IDE and MCP clients** connect as the `server` client by default.  See [IDE Integration]({{% relref "advanced/ide_integration" %}}) for how to push your GUI settings to that client.
- **External applications** choose their own ID — passed as the `client` header on chat requests, or the `client` query parameter on settings requests.

```bash
# Two callers, two isolated sessions
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "X-API-Key: $AIO_API_KEY" -H "client: team-a" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}]}'

curl -X POST http://localhost:8000/v1/chat/completions \
  -H "X-API-Key: $AIO_API_KEY" -H "client: team-b" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}]}'
```

A client ID may be 1–255 printable ASCII characters.  Path separators (`/`, `\`) and the bare components `.` and `..` are rejected.  When a request arrives with an ID the server has not seen before, a new session is created automatically by forking the configured defaults (see below).

### Reserved client IDs

| Client ID | Purpose |
|-----------|---------|
| `CONFIGURED` | The default settings template.  New clients are forked from this, and **settings** requests that omit `?client=...` operate on it directly. |
| `server` | The session used for **chat** requests that omit the `client` header — the default identity for external and IDE clients. |
| `FACTORY` | Built-in factory defaults. |

These three are **protected** — they are never evicted from the in-memory store.

{{% notice style="note" %}}
The default differs by endpoint.  Chat and history requests (which read the `client` **header**) default to `server`.  Settings requests (which read the `client` **query parameter**) default to `CONFIGURED` — so a settings call that omits `?client=...` reads or mutates the shared defaults template, **not** your external-client session.  Always send an explicit `client` when configuring a specific session.
{{% /notice %}}

### Session capacity

The server caches client sessions in memory up to the configured [`AIO_MAX_CLIENTS`]({{% relref "/configuration#server" %}}) limit. Beyond that limit, the least-recently-used session is evicted (protected clients are never evicted). An evicted client is not lost permanently — its next request simply re-creates a session from the configured defaults. Raise the limit if you expect many simultaneous users.

## What Is Shared vs. Isolated

The distinction is between the **catalog** of available resources (shared) and a client's **selection** from that catalog (isolated).

### Shared across all clients

These are configured once at the server and are common to every client:

- **Database** connections (aliases, DSNs, vector stores)
- **Model** configurations (which models exist, their endpoints and API keys)
- **OCI** profiles
- **Prompt** configurations
- The **API Server key** (`AIO_API_KEY`)

When one user adds a database or enables a model, that resource becomes part of the catalog for everyone.

### Isolated per client

Each client keeps its own working selection and runtime state:

- **Selected language model** and its parameters (temperature, max tokens, top-p, penalties)
- **Selected database** alias
- **Selected OCI** profile
- **Enabled tools** (Vector Search, NL2SQL)
- **Vector Search settings** (selected store, search type, top-k, thresholds)
- **Testbed** model selections
- **Conversation history**

So two users share the same list of databases and models, but each chooses *which* database and *which* model their own session uses, and each session keeps its own chat history under its own client ID.

{{% notice style="warning" %}}
**Client IDs partition state; they are not an access boundary.**  The `client` value is caller-supplied and is **not** authenticated or bound to a user — it only selects which session a request reads or writes.  In a deployment where several callers share one `AIO_API_KEY`, any caller that knows or guesses another ID (including `server`) can address that session and fetch its `/v1/chat/history`.  Do not rely on client IDs for privacy or tenant isolation between mutually untrusted users.  To separate untrusted tenants, run separate deployments with distinct API keys, and put network/identity controls in front of the server — see [TLS]({{% relref "advanced/tls" %}}).
{{% /notice %}}

{{% notice style="note" %}}
New sessions are forked from the `CONFIGURED` client.  In an "All-in-One" deployment you can seed external clients with your current GUI selections using **Copy Client Settings** on the [API Server]({{% relref "client/api_server" %}}) page.
{{% /notice %}}

### Example: the Racing Championship use-case

The [Racing Championship]({{% relref "use-case/racing-championship" %}}) use-case is designed to be run by a group at the same time, and it illustrates this split directly:

- Each participant opens their own GUI session — a distinct **client ID** — and plays a different driver.  Their `I am Driver <N>` turn, conversation history, and tool selections are **partitioned** by that ID, so under normal use one person's context does not bleed into another's answers.  (As noted above, this is state separation, not an enforced access boundary.)
- Everyone draws on the **shared** catalog: the same database (the `drivers`, `race_results`, and standings tables), the same enabled chat and embedding models, and a common vector store.  As the use-case notes, when several people run it together they "embed all the relevant driver docs into the same store in one pass" — one shared corpus, many isolated sessions querying it.

## Protecting Shared Configuration with a Password

Because the catalog is shared, any GUI user can, by default, change configuration that affects everyone — adding or deleting databases, editing models, resetting settings, or exporting configuration that contains secrets.  For shared or multi-user deployments, set a **shared password** to gate those controls.

Set [`AIO_CLIENT_PASSWORD`]({{% relref "/configuration#client" %}}) to enable the gate. When it is unset, the gate is disabled and all controls are accessible.

{{% notice style="note" %}}
This is a **GUI-only** access check. It does **not** replace or affect API Server authentication — external clients still authenticate with `AIO_API_KEY`. See [Environment Variables]({{% relref "configuration" %}}).
{{% /notice %}}

### What the gate covers

When a password is configured, the following remain read-only until a user signs in:

- **Configuration** tabs — Databases, Models, OCI, MCP, and Settings
- The **API Server** page (including the server key)
- Stored connection fields (passwords and keys render as a redacted `••••••••` placeholder rather than editable inputs)
- **Reset** / **Delete** actions and configuration **import/export**
- **Prompt Engineering** edits

Pages that act as personal workspaces — **ChatBot**, **Tools**, and **Testbed** — stay usable while signed out.  Only the controls on those pages that would change shared state for other users are gated.

### Signing in and out

When the gate is active, a **🔐 Sign-in** entry appears in the sidebar.  Selecting it (or the inline "Sign in" link shown next to a locked control) opens a dialog with a single password field — enter the shared password and press **Enter**.

Authentication is **per browser session**: signing in unlocks the gated controls for that session only, and other users' sessions are unaffected.  Once signed in, the entry becomes **🔓 Sign-out**, which clears the session's authenticated state.

{{% notice style="tip" %}}
The password is *shared* — a single secret distributed to the people allowed to change configuration.  It is an access gate over shared controls, not per-user identity.  For TLS and network-level hardening of a multi-user deployment, see [TLS]({{% relref "advanced/tls" %}}).
{{% /notice %}}

## Related

- [Racing Championship]({{% relref "use-case/racing-championship" %}}) — a multi-user use-case
- [API Server]({{% relref "client/api_server" %}})
- [IDE Integration]({{% relref "advanced/ide_integration" %}})
- [Environment Variables]({{% relref "configuration" %}})
- [TLS]({{% relref "advanced/tls" %}})
- [API Examples]({{% relref "advanced/api_examples" %}})
