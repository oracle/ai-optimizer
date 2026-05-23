# Racing Simulator Championship Demo — AI Optimizer

A four-step demo (with a championship-reveal finale) that shows the progressive value of the AI Optimizer using a synthetic motorsport dataset:

1. **LLM-only** — generic answers with no insight into the championship's data
2. **+ NL2SQL** — exact answers from the structured race database
3. **+ Vector Search** — coaching, briefing, and debrief context from driver documents
4. **+ Both together** — questions that need facts *and* context, answered in one turn
5. **Final Reveal — Who won the championship?** — a late Round 6 team-points insert updates the live database, then NL2SQL calculates the final champion from structured standings.

All data in this folder is synthetic. There is no PII. "Driver 1", "Driver001", and friends are simulator identities only.

---

## What's in this folder

```
racing/
├── README.md               # This runbook (the demo run-of-show)
├── schema.sql              # Oracle DDL + seed data for 100 drivers, 10 teams, Rounds 1–5
├── demo_questions.md       # Full prompt list — handout for participants
├── prompts.json            # AI Optimizer prompt bundle (motorsport persona + NL2SQL/RAG guidance)
└── corpus/
    ├── driver_001.md       # Per-driver briefing + coaching notes + debrief
    ├── driver_002.md
    ├── ...
    └── driver_100.md
```

---

## Before your first run

### Infrastructure
1. **Kubernetes** - apply the OpenTofu Kubernetes stack for the target environment.  CPU is perfectly fine.
1. **Load the schema** — as the `AI_OPTIMIZER` database user, run `schema.sql`. It creates the `teams`, `drivers`, `races`, `race_results`, `pit_stops`, `incidents`, `performance_metrics`, and `team_race_points` tables; the `driver_standings`, `team_standings`, `championship_team_standings`, and `race_summary` views; and seeds Rounds 1–5 for all 100 drivers across 10 teams. Round 6 is scheduled but has **no** team points in the bootstrap database — that's intentional.
1. **Verify Schema** — pick a driver number (e.g. Driver 1) and confirm in SQL that they exist and have results before Round 6:
   ```sql
   SELECT driver_label, team_id FROM drivers WHERE driver_code = 'Driver001';
   SELECT COUNT(*) FROM race_results rr JOIN drivers d USING (driver_id)
   WHERE d.driver_code = 'Driver001';
   ```

### AI Optimizer
Log into the AI Optimizer to setup:

1. **Pick an LLM + embedding model** at **Configuration → Models**. Anything with solid tool-use works (e.g. OpenAI `gpt-4o` + `text-embedding-3-small`, or OCI `cohere.command-r-plus` + `cohere.embed-english-v3.0`). For an on-prem fallback, Ollama `llama3.1:8b` + `mxbai-embed-large` works, though combined-mode tools is weaker.
1. **Import the prompts** — in **Tools → 🎤 Prompts**, import `prompts.json`. This installs the motorsport-analyst persona and the NL2SQL/RAG guidance the demo relies on.
1. **Helm** - apply `docs/demo/racing/values-oke-demo-100.yaml` (capacity overlay sized for ~100 concurrent attendees).


Embedding the driver documents happens **during** the demo (Step 3). Loading the finale points happens **during** the Final Reveal by running `finale_insert.sql`.

---

## Demo flow

Open the **ChatBot** page. Each participant should pick a driver number 1–100 and use it consistently. The demo prompts below use `<N>` — replace with the participant's driver number.

The full prompt list is in `demo_questions.md` — print or share it so the audience can follow along.

### Step 1 — LLM-only (the "good failure")

**Settings:** Vector Search **off**, NL2SQL **off**.

**Prompts:**
> I am Driver `<N>`. What is my driving style?
>
> I am Driver `<N>`. What team am I on?
>
> I am Driver `<N>`. How many championship points do I have?

**Expected behavior:** The model either refuses, hedges, or hallucinates. It has no idea who Driver `<N>` is in this championship.

**Talking point:** "The model is smart, but it has no idea what 'Driver `<N>`' means in our world. Let's connect it to the data."

---

### Step 2 — Add NL2SQL

**Settings:** NL2SQL **on**, database connection **CORE** selected.

**Prompts (same identity, real answers now):**
> I am Driver `<N>`. What is my driving style, vehicle setup, and team?
>
> I am Driver `<N>`. How many points do I have before the finale?
>
> I am Driver `<N>`. What was my best finish, and my fastest lap?
>
> Compare Driver `<N>` with Driver `<M>` on total points, best finish, average lap time, and incidents.
>
> Which team is leading before Round 6?

**Expected behavior:** The agent calls SQLcl and runs queries against `drivers`, `race_results`, and the `driver_standings` / `team_standings` views — returning exact numbers for the driver and the championship through Round 5.

**Talking point:** "Real-time, against the live database. No nightly extract, no stale dashboard. Note what it *can't* answer though — anything about coaching, debriefs, or Round 6 before the final insert."

---

### Step 3 — Add Vector Search

**Settings:** Vector Search **on** (point at the driver-documents vector store), NL2SQL **off**.

**One-time, in front of the audience:** in **Tools → 📚 Split/Embed**, upload `corpus/driver_<NNN>.md` for the participant's driver (e.g. `driver_001.md` for Driver 1) into a vector store table (suggest `DRIVER_DOCS`). For a small group, embed all the driver docs the participants need at once.

**Prompts:**
> I am Driver `<N>`. Summarize my driver briefing.
>
> I am Driver `<N>`. What did my coach say I should improve?
>
> I am Driver `<N>`. What setup advice was given to me?
>
> I am Driver `<N>`. What risks or weaknesses are mentioned in my notes?
>
> I am Driver `<N>`. Give me three practical focus areas for my next simulator session.

**Expected behavior:** The model retrieves the participant's driver doc and answers in the voice of a race engineer — naming the specific corner phases, tyre calls, and coaching priorities written for that driver.

**Talking point:** "Same model, same chat, completely different answer. We just grounded it in the team's own coaching notes — no fine-tuning, no retraining."

---

### Step 4 — Both together

**Settings:** Vector Search **on**, NL2SQL **on**.

**Prompts:**
> I am Driver `<N>`. Use my database results and my documents to summarize my season so far.
>
> I am Driver `<N>`. Based on my points, incidents, and coaching notes, what should I focus on next?
>
> I am Driver `<N>`. Did my structured performance match the feedback in my documents?
>
> Compare Driver `<N>` with Driver `<M>` using both database results and driver notes.

**Expected behavior:** The combined-mode orchestrator routes to both tools and synthesizes. The answer cites SQL-derived facts (points, finishes, lap times) and weaves in the coaching narrative (what the debrief said about those results).

**Talking point:** "Neither side alone gets here. The numbers are in the database; the *story* is in the documents. The answer the driver actually wants needs both."

---

### Final Reveal — Who won the championship?

**Settings:** NL2SQL **on**, database connection **CORE** selected. Vector Search can be off for this step.

**One-time, in front of the audience:** run `finale_insert.sql` as the `AI_OPTIMIZER` database user. This inserts the final Round 6 team points into `team_race_points` and makes them visible through `championship_team_standings`.

```sql
@docs/demo/racing/finale_insert.sql
```

**Prompts:**
> Using the database championship standings, which team won the championship? Show the pre-finale points, the Round 6 points, and the final total.
>
> Which teams were in contention before Round 6, and how did the final Round 6 database insert change the result?
>
> Why could NL2SQL not answer the final championship winner before the Round 6 insert?
>
> Show me the SQL used to calculate the final championship standings.

**Expected behavior:** The model queries `championship_team_standings`, shows pre-finale team points, Round 6 points, and final totals, then names the champion. Before `finale_insert.sql` runs, Round 6 points are zero and the final champion is not available.

This is the money shot for live operational data: the same question changes when the late structured result lands in the database, and the model can explain the calculation from the underlying SQL.

**Talking point:** "This is the question that proves the database is live. We did not re-index documents or rebuild a dashboard — the final classification arrived as structured data, and the assistant calculated the championship from it."

---

## More questions to try

Variations on each step, organized by what they demonstrate. Pick based on what your audience cares about — engineering, coaching, strategy.

### NL2SQL variations (Step 2)

| Prompt | Why ask it |
|---|---|
| "Which drivers have the same driving style as Driver `<N>`?" | `WHERE driving_style = (SELECT ...)`. Shows the model handling correlated lookups. |
| "What is my team engineering focus?" | Two-table join (`drivers → teams`). Trivially small, easy to verify on screen. |
| "Did I have any incidents? How many pit stops did I make?" | Aggregates over `incidents` and `pit_stops`. |
| "Which race had the highest field average lap time?" | Uses the `race_summary` view — a clean view-vs-raw-table comparison. |
| "Which team has the most incidents this season?" | `GROUP BY` over `team_standings.incident_count`. Strategy/risk angle. |

### Vector Search variations (Step 3)

| Prompt | Why ask it |
|---|---|
| "What does my race debrief say?" | Pulls the engineer's debrief paragraph — closest to a "what would my coach tell me" voice. |
| "What setup advice was given to me?" | Tests retrieval on a specific section of the driver doc. |
| "What does my brief say about overtaking opportunities?" | Cross-section pull — answer is woven across briefing and coaching notes. |

### Combined-mode variations (Step 4)

| Prompt | Why ask it |
|---|---|
| "Which race should I review first, based on my worst structured result and my debrief notes?" | Joins a SQL ranking with a document recommendation. |
| "Did my structured performance match the feedback in my documents?" | The most interesting answer in the deck — sometimes the model finds a contradiction. |
| "Compare Driver `<N>` with Driver `<M>` using both database results and driver notes." | Two drivers, two sources each — stress-tests the orchestrator. |

### Improv moment (always lands)

After Step 4, before the Final Reveal: **"Pick any driver number and ask anything."** Hands-on audiences love this because they're already invested in their own driver — peer comparisons get competitive fast. Keep a notepad of what they ask; those become the next demo's scripted prompts.

---

## Troubleshooting

- **Step 2 returns empty results or asks for column names:** confirm `prompts.json` was imported. The racing-tuned `optimizer_nl2sql-tools-default` includes the demo schema and tells the agent to run SQL directly. Re-import if Step 2 is flaky.
- **Step 2 invents Round 6 results or a champion:** the model is over-reaching. The racing NL2SQL prompt explicitly forbids this — re-import `prompts.json` and try again.
- **Step 3 says "no relevant sources":** the vector store is empty for that driver, or the embedding model differs from the one used at retrieval time. Re-embed the participant's `corpus/driver_<NNN>.md` using the same model that's selected in **Configuration → Models**.
- **Step 4 answers from only one tool:** the classifier picked one path. Re-phrase to make the dual-source nature explicit ("using both my database results and my documents..."). On the Ollama fallback, this is more common — local models have weaker tool-use.
- **Final Reveal names the wrong champion or refuses:** confirm `finale_insert.sql` was run and that `championship_team_standings` returns non-zero `round6_points` for each team.
- **Driver identifier ambiguity** (e.g. "Driver 1" matches multiple rows): switch to the padded code (`Driver001`). The racing prompt tells the model to normalize, but smaller models slip.

---

## Resetting between runs

To re-run from scratch:

```sql
-- In the schema with the vector store
DROP TABLE DRIVER_DOCS PURGE;
```

Then re-run `schema.sql`, re-embed `corpus/driver_<NNN>.md` during Step 3, and run `finale_insert.sql` during the Final Reveal. If you customized any prompts, click **Restore Default** on each one — the originals will be re-installed from `prompts.json` on the next import.
