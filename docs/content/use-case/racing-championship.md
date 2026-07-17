+++
title = 'Racing Championship'
weight = 10
description = 'Ground an LLM step by step (NL2SQL, Vector Search, then both) against a synthetic 100-driver racing championship, ending with a live championship reveal.'
+++

<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore briefing briefings cohere debrief debriefs Donington kerb kerbs llama mxbai NL2SQL ollama Oulton qualifying relref Silverstone Snetterton sqlcl sqlplus standings Thruxton tyre tyres undercut vecsearch
-->

This use-case is a synthetic Racing Simulator Championship. You'll play the role of a driver in a 100-driver, 20-team season and ask the same questions four different ways, watching the answers improve as each grounding mechanism is added.

## What You'll See

| Step | Settings | What it demonstrates |
|------|----------|----------------------|
| 1. **LLM-only** | NL2SQL off, Vector Search off | The model has no idea who your driver is, so it refuses, hedges, or hallucinates. |
| 2. **+ NL2SQL** | NL2SQL on | Exact answers from `drivers`, `race_results`, and `driver_standings` via SQLcl MCP. |
| 3. **+ Vector Search** | Vector Search on, NL2SQL off | Coaching, briefing, and debrief context retrieved from per-driver Markdown notes. |
| 4. **Both together** | NL2SQL on, Vector Search on | Questions that need both facts and context, answered in one turn. |
| Final Reveal | NL2SQL on | A late Round 6 insert updates the live database, and the assistant calculates the championship from the new structured standings. |

## Before You Begin

You'll need:

- A configured {{% short_app_ref %}} from the [Walkthrough]({{% relref "/walkthrough" %}}), or any equivalent install where you have an enabled chat model, an enabled embedding model, and a [database connection]({{% relref "/client/configuration/databases" %}}).
- A chat model with solid tool use. The demo has been tuned against the on-premises models used in the [Walkthrough]({{% relref "/walkthrough" %}}): [Ollama](https://ollama.com/) `granite4.1:8b` with `mxbai-embed-large`.
- An Oracle AI Database connection with rights to create tables and views (the `DB_DEVELOPER_ROLE` granted in the Walkthrough is sufficient).
- The [SQLcl MCP Server]({{% relref "/client/configuration/mcp/#sqlcl-mcp-server-nl2sql" %}}) configured for **NL2SQL**, pointed at the same database.

## Setup

Everything you need lives under [`docs/demo/racing-championship/`](https://github.com/oracle/ai-optimizer/tree/main/docs/demo/racing-championship) in the source repository:

| File | Purpose |
|------|---------|
| [`schema.sql`](https://github.com/oracle/ai-optimizer/blob/main/docs/demo/racing-championship/schema.sql) | Oracle DDL plus seed data for 20 teams, 100 drivers, and Rounds 1–5. Round 6 is scheduled but has no team points yet. |
| [`prompts.json`](https://github.com/oracle/ai-optimizer/blob/main/docs/demo/racing-championship/prompts.json) | A motorsport-analyst prompt bundle that tunes the **NL2SQL**, **Vector Search**, and combined-mode prompts for this dataset. |
| [`corpus/`](https://github.com/oracle/ai-optimizer/tree/main/docs/demo/racing-championship/corpus) | 100 per-driver Markdown briefings used in Step 3. |
| [`finale_insert.sql`](https://github.com/oracle/ai-optimizer/blob/main/docs/demo/racing-championship/finale_insert.sql) | The late Round 6 team-points insert used during the Final Reveal. |

If you extracted the source tarball during the Walkthrough, you already have these in `docs/demo/racing-championship/`. Otherwise, download the files individually from the links above.

### 1. Load the schema

Connect to your Oracle AI Database as the user the {{% short_app_ref %}} is configured to use, and run `schema.sql`. 

If you are using the database created during the [Walkthrough]({{% relref "/walkthrough" %}}), it runs in a container that can't see your local checkout, so copy the demo files into the container first and then load the script from inside it:

```bash
podman cp docs/demo/racing-championship ai-optimizer-db:/tmp/racing-championship
podman exec -it ai-optimizer-db sqlplus '<AIO_DB_USERNAME>/<AIO_DB_PASSWORD>@<AIO_DB_DSN>'
```

Where `AIO_DB_USERNAME`, `AIO_DB_PASSWORD`, and `AIO_DB_DSN` are the database authentication and connection string values.

```sql
@/tmp/racing-championship/schema.sql
```

`schema.sql` is safe to re-run: it drops the demo tables first, then recreates the tables and views used for the NL2SQL structured queries. It also seeds Rounds 1–5 for all 100 drivers.

The per-team strength factor is randomized on every reset, so the pre-finale standings and the eventual champion change each time you re-run the script.

### 2. Verify the seed

Pick a driver number from 1 through 100. That is your driver for the rest of the use-case. Confirm the row exists and has results before Round 6:

```sql
SELECT driver_label, team_id FROM drivers WHERE driver_code = 'Driver001';

SELECT COUNT(*) FROM race_results rr JOIN drivers d USING (driver_id)
WHERE d.driver_code = 'Driver001';
```

### 3. Import the prompts

In the {{% short_app_ref %}}, navigate to **Tools → 🎤 Prompts** and "Upload" `docs/demo/racing-championship/prompts.json`. 

This installs:
- A motorsport-analyst system prompt
- An **NL2SQL** prompt
- A **Vector Search** prompt that grounds answers in the retrieved driver documents
- A combined-mode classifier and synthesis prompt that routes structured vs. narrative asks

See [Prompt Engineering]({{% relref "/client/tools/prompt_eng" %}}) for more on managing prompts.

### 4. Enable Models

Enable the Language and Embedding Models (if not already).  In the {{% short_app_ref %}}, navigate to **Configuration → 🤖 Models**. 

The demo has been tuned against the on-premises models used in the [Walkthrough]({{% relref "/walkthrough" %}}): [Ollama](https://ollama.com/) `granite4.1:8b` with `mxbai-embed-large`. Other Language Models may work, especially larger ones, but may require some prompt engineering.

See [Model Configuration]({{% relref "/client/configuration/models" %}}) for more on configuring models.


### 5. Decide your Driver Number

Decide on a driver number `<N>` between 1 and 100. Replace prompts below that use `<N>` with the number you have chosen (for example, `Driver 7`).  

A few prompts also use `<M>` for any other driver you want to compare against.

## Demo Flow

### Step 1: LLM-only

{{% notice style="code" title="Settings" icon="flag-checkered" %}}
_Vector Search_ **off**, _NL2SQL_ **off**
{{% /notice %}}

Introduce yourself:
```text
I am Driver <N>
```

#### Ask:
```text
What is my driving style?

How many championship points do I have?

What team am I on?
```

**What to look for:** the model either refuses, hedges, or makes up an answer. It has no idea who Driver `<N>` is in this championship.

> The model is capable, but it has no idea what "Driver `<N>`" means in this championship. Next, we connect it to the data.

### History and Context

Every prompt from here on refers to you in the first person ("my", "I", "me"). The assistant only knows that "I" means Driver `<N>` because your `I am Driver <N>` turn is still in the conversation.

The [_History and Context_]({{% relref "/client/chatbot#history-and-context" %}}) toggle in the sidebar controls this:

- **On**: the whole context window is sent to the model.
- **Off**: only your latest message is sent.

**Try it both ways.** Turn _History and Context_ **off** and #### Ask:

```text
What driver am I?
```

With only the current message in scope, the assistant can't tell. Now turn it **on**, ask the same question again, and it answers `Driver <N>`.

**What to look for:** the assistant can only resolve "I", "my", and "me" while the earlier turn is still in context.

**Why this matters for the rest of the demo.** Think of the context window as everything the model can see when it answers. It fills from two places:

- **History puts the question in context.** Keeping the conversation in the window is how the assistant knows "my" means Driver `<N>`.
- **The tools put the facts in context.** When you switch on a tool, the assistant turns your question into a lookup, and whatever it finds (the rows from the database, or your notes from the vector store) is added to the same window.

The model answers from what it sees in that window, which is why the response is grounded in real data instead of guessed. With _History and Context_ **off**, the tools can't tell who "I" am, so they look up the wrong driver or come back empty.

> Leave _History and Context_ **on** for the rest of the use-case. Use the **Clear History** button only when you want to start over as a different driver.

### Step 2: Add NL2SQL

{{% notice style="code" title="Settings" icon="flag-checkered" %}}
_Vector Search_ **off**, _NL2SQL_ **on**
{{% /notice %}}

Ask again (ensure _History and Context_ is **on**):
```text
What team am I on?
```

Compare the answer the model gave without NL2SQL with the new answer.  The response is now grounded with data from the **Oracle AI Database**!

Follow-up with some additional questions:
```text
What is my driving style, vehicle setup, and team?

Compare Driver <M> with me on total points, best finish, average lap time, and incidents.

Which team is leading before Round 6?

Summarize my driver briefing.
```

**What to look for:** the agent calls SQLcl and queries `drivers`, `race_results`, and the `driver_standings` / `team_standings` views, returning exact numbers for your driver and the championship through Round 5. For `Summarize my driver briefing.`, with only _NL2SQL_ enabled, it should say that the structured database does not have that information.

> These answers come from the live database in real time, not a nightly extract or a stale dashboard. But notice what it can't answer yet: anything about coaching, debriefs, or Round 6 before the final insert.

### Step 3: Add Vector Search

{{% notice style="code" title="Settings" icon="flag-checkered" %}}
_Vector Search_ **on**, _NL2SQL_ **off**
{{% /notice %}}

Before asking, embed your driver document into a vector store. In **Tools → 📚 Split/Embed**:

1. Select **Create New Vector Store**.
2. Set **Knowledge Base Source** to `Local` and upload `corpus/driver_<NNN>.md` for your driver (e.g. `corpus/driver_007.md` for Driver 7).
3. Use an **Embedding Alias** such as `DRIVER_DOCS`.
4. Click **Populate Vector Store**.

If multiple people are running the use-case together, embed all the relevant driver docs into the same store in one pass.

#### Ask:

{{% notice style="code" title="Say What?" icon="face-surprise" %}}
If using a small model, or on a CPU, you can try to enable "Prompt Rephrase".  

If the model cannot cope with rephrasing, disable it and change each query to include your driver #, for example:

**I am Driver `<N>`**; Summarize my driver briefing.
{{% /notice %}}

```text
Summarize my driver briefing.

What did my coach say I should improve?

What setup advice was given to me?

What risks or weaknesses are mentioned in my notes?

Give me three practical focus areas for my next simulator session.
```

**What to look for:** the model retrieves your driver doc and answers in the voice of a race engineer, naming the specific corner phases, tyre calls, and coaching priorities written for your driver.

> It's the same model and the same chat, but the answer is completely different, because we grounded it in the team's own coaching notes without any fine-tuning or retraining.

### Step 4: Both Together

{{% notice style="code" title="Settings" icon="flag-checkered" %}}
_Vector Search_ **on**, _NL2SQL_ **on**
{{% /notice %}} 

#### Ask:
```text
Use my database results and my documents to summarize my season so far.

Based on my points, incidents, and coaching notes, what should I focus on next?

Did my structured performance match the feedback in my documents?

Compare Driver <N> with Driver <M> using both database results and driver notes.
```

**What to look for:** the combined-mode orchestrator routes each question to both tools and synthesizes a single answer. It cites SQL-derived facts (points, finishes, lap times) and weaves in the coaching narrative (what the debrief said about those results).

> Neither tool gets here alone. The numbers live in the database and the story lives in the documents; the answer the driver actually wants needs both.

### Final Reveal: Who Won the Championship?

{{% notice style="code" title="Settings" icon="flag-checkered" %}}
_Vector Search_ **on**, _NL2SQL_ **on**
{{% /notice %}} 

Before this step, ask the model who won the championship. With no Round 6 results loaded, the prompt instructs the model to say the finale has not been recorded yet and to refuse to name a winner.

Now load the Round 6 team points. As the same database user, run the script copied into the container during Setup (re-run the `podman cp` from Step 1 first if you have restarted the database container since):

```sql
@/tmp/racing-championship/finale_insert.sql
```

This inserts the final Round 6 team points into `team_race_points` and makes them visible through `championship_team_standings`.

#### Ask:

```text
Using the database championship standings, which team won the championship? Show the pre-finale points, the Round 6 points, and the final total.

Which teams were in contention before Round 6, and how did the final Round 6 database insert change the result?

Why could NL2SQL not answer the final championship winner before the Round 6 insert?

Show me the SQL used to calculate the final championship standings.
```

**What to look for:** the model queries `championship_team_standings`, presents pre-finale team points, Round 6 points, and final totals as a table, and names the champion. It will also explain why it couldn't answer this question a few minutes earlier.

> This is the question that proves the database is live. We didn't re-index documents or rebuild a dashboard. The final classification arrived as structured data, and the assistant calculated the championship from it.

## More Questions to Try

Variations on each step, organized by what they demonstrate.

### NL2SQL variations (Step 2)

| Prompt | Why ask it |
|--------|------------|
| Which drivers have the same driving style as Driver `<N>`? | `WHERE driving_style = (SELECT ...)`. Correlated lookup. |
| What is my team's engineering focus? | Two-table join (`drivers → teams`). Trivial to verify on screen. |
| Did I have any incidents? How many pit stops did I make? | Aggregates over `incidents` and `pit_stops`. |
| Which race had the highest field average lap time? | Uses the `race_summary` view, a clean view-vs-raw-table comparison. |
| Which team has the most incidents this season? | `GROUP BY` over `team_standings.incident_count`. |

### Vector Search variations (Step 3)

| Prompt | Why ask it |
|--------|------------|
| What does my race debrief say? | Pulls the engineer's debrief paragraph. |
| What setup advice was given to me? | Tests retrieval on a specific section of the driver doc. |
| What does my brief say about overtaking opportunities? | Cross-section pull; the answer is woven across the briefing and coaching notes. |

### Combined-mode variations (Step 4)

| Prompt | Why ask it |
|--------|------------|
| Which race should I review first, based on my worst structured result and my debrief notes? | Joins a SQL ranking with a document recommendation. |
| Did my structured performance match the feedback in my documents? | The most interesting answer here; sometimes the model finds a contradiction. |
| Compare Driver `<N>` with Driver `<M>` using both database results and driver notes. | Two drivers, two sources each; stress-tests the orchestrator. |

## Troubleshooting

- **Step 2 returns empty results or asks for column names:** confirm `prompts.json` was imported. The racing-tuned `optimizer_nl2sql-tools-default` prompt includes the demo schema and tells the agent to run SQL directly. Re-import if Step 2 is flaky.
- **Step 2 invents Round 6 results or a champion:** the model is over-reaching. The racing **NL2SQL** prompt explicitly forbids this, so re-import `prompts.json` and try again.
- **Step 3 says "no relevant sources":** the vector store is empty for that driver, or the embedding model differs from the one used at retrieval time. Re-embed the participant's `corpus/driver_<NNN>.md` using the same model selected in **Configuration → Models**.
- **Step 4 answers from only one tool:** the classifier picked one path. Re-phrase to make the dual-source nature explicit (`...using both my database results and my documents...`). This is more common with smaller local models because they have weaker tool use.
- **Final Reveal names the wrong champion or refuses:** confirm `finale_insert.sql` ran and that `championship_team_standings` returns non-zero `round6_points` for each team.
- **Driver identifier ambiguity** (e.g. `Driver 1` matches multiple rows): switch to the padded code (`Driver001`). The racing prompt tells the model to normalize, but smaller models slip.

## Resetting Between Runs

To re-run the use-case from scratch:

```sql
-- In the schema that holds the vector store, replacing DRIVER_DOCS with
-- whatever Embedding Alias you used.
DROP TABLE DRIVER_DOCS PURGE;
```

Then re-run `schema.sql`, re-embed `corpus/driver_<NNN>.md` during Step 3, and run `finale_insert.sql` during the Final Reveal. If you customized any of the racing prompts in the {{% short_app_ref %}}, click **Restore Default** on each, and the originals will be re-installed from `prompts.json` on the next import.

Because `schema.sql` randomizes per-team form on every reset, the pre-finale standings and the eventual champion change each time. This is intentional: it keeps the Final Reveal genuinely unknown right up to the moment you load the Round 6 points.

## What's Next?

- Build your own use-case. Swap in your own DDL and seed data, write a `prompts.json` that teaches the model your schema, and curate a document corpus that mirrors the qualitative side of your domain. The four-step progression (**LLM-only → NL2SQL → Vector Search → both**) is reusable.
- Try the [Testbed]({{% relref "/client/testbed" %}}) to evaluate the same questions against different models, prompts, or embedding strategies.
- Read [Agents and Flows]({{% relref "/agents" %}}) to understand how the {{% short_app_ref %}} routes each turn between the **NL2SQL** agent, the **Vector Search** flow, and the combined-mode classifier.
