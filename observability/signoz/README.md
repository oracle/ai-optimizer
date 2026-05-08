<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore signoz openinference clickhouse promql
-->

# SigNoz Starter Assets

Curated dashboards and alert rules for the AI Optimizer server, suitable for a fresh [SigNoz](https://signoz.io) install. The committed JSON files are the **source of truth**: SigNoz stores its own state in ClickHouse / Postgres volumes that are wiped on a re-install, so anything not committed here is lost.

The dashboards and alerts live under `helm/observability/signoz/` so they ship alongside the Helm chart that deploys SigNoz; the loader script lives here in `observability/signoz/`:

```
helm/observability/signoz/
├── dashboards/
│   └── ai-optimizer-overview.json     # Service health + LLM usage at a glance
└── alerts/
    ├── error-rate-spike.json          # 5xx response rate > 1% sustained
    ├── latency-p95-breach.json        # /v1/chat/completions p95 > 10s sustained
    └── telemetry-silence.json         # No traces from the server for 10 minutes

observability/signoz/
└── bootstrap-signoz.py                # Load dashboards + alerts via SigNoz's API
```

## Loading the assets into SigNoz

### Bootstrap script (recommended)

One script loads both dashboards and alerts via SigNoz's HTTP API. Pass the admin credentials you set on first UI visit; the script prompts for your password and logs in for you:

```bash
observability/signoz/bootstrap-signoz.py \
  --host http://localhost:8080     \
  --email admin@example.com
# SigNoz password for admin@example.com: ********
```

The script POSTs the credentials to `/api/v2/sessions/email_password`, captures the returned `data.accessToken`, and uses it for the dashboard / alert API calls — no separate token-fetch step needed. Password input is supported via the interactive prompt or the `SIGNOZ_PASSWORD` env var; the script intentionally does not provide a `--password` flag.

For CI or SSO setups that don't fit the email/password flow, pass a pre-fetched JWT:

```bash
observability/signoz/bootstrap-signoz.py \
  --host http://localhost:8080     \
  --token <jwt>
```

Each flag has a matching environment variable for non-interactive use:

| Flag | Env var | Notes |
|---|---|---|
| `--host` | `SIGNOZ_HOST` | Required |
| `--email` | `SIGNOZ_EMAIL` | Required unless `--token` is set |
| (none — prompt) | `SIGNOZ_PASSWORD` | Set this for non-interactive runs (e.g. CI) |
| `--token` | `SIGNOZ_TOKEN` | Bypasses the login step |
| `--org-id` | `SIGNOZ_ORG_ID` | Required only when the email belongs to multiple SigNoz orgs (rare). Single-org installs auto-discover. |

The script reports per-file success/failure and exits non-zero if anything fails. To load only one kind, use `--dashboards-only` or `--alerts-only` (mutually exclusive).

After loading, open each alert in the UI and attach your notification channel (Slack/email/PagerDuty) — the committed JSON leaves `preferredChannels` empty.

> **Re-running creates duplicates.** SigNoz assigns a new id per POST, so a second run of the script produces a second copy of every dashboard/alert. The intended workflow is: bootstrap once into a fresh install; further changes happen in the UI; export back to this directory; on a re-install (post `compose down -v`), bootstrap again into the new empty install. To force a refresh against a non-empty install, delete the existing items in the UI first.

> **Send a real chat request before bootstrapping.** SigNoz lazily indexes span attribute keys: a key is unknown to the dashboard validator until it has been seen in at least one ingested span. The LLM panels filter on `llm.model_name`, which only enters the index after a chat completion has produced an LLM span. A `/v1/healthz` curl is **not** sufficient — only HTTP keys get indexed from healthz traffic.
>
> Workflow:
>
> 1. With OTel enabled and SigNoz running, hit a chat endpoint:
>    ```bash
>    curl -X POST http://localhost:8000/v1/chat/completions \
>      -H "X-API-Key: $AIO_API_KEY" \
>      -H "Content-Type: application/json" \
>      -d '{"messages":[{"role":"user","content":"hello"}]}'
>    ```
> 2. Wait ~30 seconds for the OTel batch span processor to flush and SigNoz to register the new keys.
> 3. Then run `bootstrap-signoz.py`.
>
> Symptoms of bootstrapping too early: errors like `key 'llm.model_name' not found while parsing the search expression`. Re-run after step 2 succeeds.

### Manual paths

If you'd rather not script:

- **Dashboards** can be imported via the SigNoz UI: **Dashboards → New dashboard → Import JSON**, then select `helm/observability/signoz/dashboards/ai-optimizer-overview.json`.
- **Alerts cannot.** SigNoz's UI does not support JSON import for alerts (only dashboards). Either run the bootstrap script, or recreate each alert by hand in **Alerts → New Alert** using the JSON file as a reference. Field-to-UI mapping for hand recreation:

| JSON field | UI field |
|---|---|
| `alert` | Alert name |
| `alertType` | Alert type (`TRACES_BASED_ALERT`, `LOGS_BASED_ALERT`, `METRIC_BASED_ALERT`) |
| `condition.compositeQuery.queries[]` (each `spec`) | Per-query: signal, filter expression, aggregation expression |
| `condition.compositeQuery.queries[]` (`type: builder_formula`) | Formula (only used by `error-rate-spike`) |
| `condition.selectedQueryName` | The query/formula whose result is compared to the threshold |
| `condition.thresholds.spec[].op` | Comparison operator (`above`, `below`, `above_or_equal`, `below_or_equal`) |
| `condition.thresholds.spec[].target` + `targetUnit` | Threshold value + unit |
| `condition.thresholds.spec[].matchType` | Match condition (`at_least_once`, `all_the_times`, `on_average`, `in_total`, `last`) |
| `evaluation.spec.evalWindow` | Evaluation window |
| `evaluation.spec.frequency` | Evaluation frequency |
| `annotations.summary` / `description` | Alert text shown when firing |

The exact API endpoint paths track the SigNoz version; if the bootstrap script returns 404 for `/api/v1/dashboards` or `/api/v2/rules`, consult the SigNoz API docs and adjust the script.

## Updating the assets

When you change a dashboard or alert in the UI:

1. Use the SigNoz UI's **Export JSON** action on the dashboard or alert.
2. Replace the corresponding file under `helm/observability/signoz/dashboards/` or `helm/observability/signoz/alerts/`.
3. Open a PR. The committed file is the version other operators will load.

This makes the assets a small but real piece of the codebase rather than a one-time gift, and prevents the situation where one operator's improvements live only in their personal SigNoz instance.

## Compatibility

The bootstrap script and committed JSON target **SigNoz 0.121+**. The script authenticates via `POST /api/v2/sessions/email_password` and uploads alerts to `POST /api/v2/rules`; the committed alerts use SigNoz's v5 / `v2alpha1` schema (`alertType`, `condition.compositeQuery.queries[]`, `condition.thresholds`).

If you upgrade to a future SigNoz that changes either the API paths or the alert schema, regenerate the JSON via the export-and-commit workflow described under [Updating the assets](#updating-the-assets).

If a dashboard fails to import:

- Open the JSON in the UI's **Edit** view to see which panel/query SigNoz rejects.
- Recreate the offending panel manually using the description in [`helm/observability/signoz/dashboards/ai-optimizer-overview.json`](../../helm/observability/signoz/dashboards/ai-optimizer-overview.json) (each widget has a `description` field).
- Export and overwrite the committed file.

## Attributes the dashboards rely on

These attributes are emitted by the server's instrumentation; the panels filter and group on them. If you change instrumentation in a way that drops or renames any of these, the corresponding panel will go empty.

| Attribute | Source | Used by |
|---|---|---|
| `service.name = ai-optimizer-server` | OTel resource | All panels |
| `http.route` | FastAPI instrumentor | Request rate / latency / error rate by route |
| `http.status_code` | FastAPI instrumentor | Error rate panels |
| `llm.model_name` | OpenInference LangChain instrumentor | LLM call rate panel (filter `exists`), token panel grouping |
| `llm.token_count.total` | OpenInference LangChain instrumentor | Token sum panel |
| `openinference.span.kind` | OpenInference LangChain instrumentor | Not used by panels in v1 — see note below |

The `openinference.span.kind` attribute is emitted on every OpenInference span (`LLM`, `RETRIEVER`, `EMBEDDING`, etc.) but the v1 dashboard does not depend on it. Filtering by `llm.model_name exists` covers LLM spans without needing that key indexed, which matters because `openinference.span.kind` takes longer to register in SigNoz than `llm.model_name` after the first traffic. To add an embedding-latency panel, recreate it manually in the UI once your install has indexed `openinference.span.kind`: filter on `openinference.span.kind = EMBEDDING`, aggregate p95 of `durationNano`. Then export the dashboard JSON and overwrite `helm/observability/signoz/dashboards/ai-optimizer-overview.json`.

For a fuller catalog of what each span carries, see [Reading Traces](../../docs/content/observability/reading-traces.md).
