# Bank Mortgage Demo — AI Optimizer

A four-act demo (with an optional fifth) that shows the progressive value of the AI Optimizer using synthetic mortgage data:

1. **LLM-only** — generic answers with no insight into the bank's data
2. **+ Vector Search** — answers grounded in the bank's policy and product documents
3. **+ NL2SQL** — real-time answers from operational mortgage data
4. **+ Both together** — questions that need both, answered in one turn
5. **Tune for your bank** *(optional)* — show the prompt-engineering surface

All data in this folder is synthetic. There is no PII.

---

## What's in this folder

```
mortgage/
├── README.md                         # This runbook (the demo run-of-show)
├── PREREQ.md                         # One-time setup — do this first
├── schema.sql                        # Oracle DDL + ~36 mortgages of seed data
└── corpus/
    ├── 01-product-catalog.md         # Mortgage product descriptions
    ├── 01-product-catalog.html       # Same content, browser-friendly for screen-share
    ├── 02-underwriting-policy.md
    ├── 02-underwriting-policy.html
    ├── 03-customer-faq.md
    └── 03-customer-faq.html
```

---

## Before your first run

Complete every step in **`PREREQ.md`**. It covers the database user, schema load, AI Optimizer wiring, model selection, and corpus embedding. Skip any step and the demo will not behave as described below.

---

## Demo flow

Open the **ChatBot** page. The audience sees a fresh chat with a mode toggle in the sidebar.

### Act 1 — LLM-only (the "good failure")

**Settings:** Vector Search **off**, NL2SQL **off**.

**Prompt:**
> What mortgage products do we offer and what are the eligibility rules?

**Expected behavior:** The LLM gives a generic, hedged answer about typical mortgage products. It cannot know what *your* bank offers. 

**Talking point:** "The model is smart, but it has no idea who we are. Let's give it our documents."

---

### Act 2 — Add Vector Search

**Settings:** Vector Search **on** (point at `MORTGAGE_DOCS`), NL2SQL **off**.

**Prompt (same as Act 1):**
> What mortgage products do we offer and what are the eligibility rules?

> Do we charge a prepayment penalty?

**Expected behavior:** The model now lists `FIXED30-PRIME`, `ARM5_1-STD`, `JUMBO15-PRIME`, `FHA-30YR`, with the actual minimum credit scores, max LTVs, and DTI thresholds from the policy document.

If you want the audience to see the source material, open the corresponding `corpus/*.html` file in a second browser window alongside the chat.

**Talking point:** "Same question, completely different answer. We just grounded the model in our own knowledge — no fine-tuning, no model training."

---

### Act 3 — Add NL2SQL

**Settings:** Vector Search **off**, NL2SQL **on**, database connection **MORTGAGE** selected.

**Prompt:**
> How many active mortgages do we have on the FIXED30-PRIME product, and what's the average rate?

**Expected behavior:** The agent calls SQLcl, runs a query roughly equivalent to:

```sql
SELECT COUNT(*), ROUND(AVG(interest_rate), 2)
FROM   mortgages
WHERE  product_code = 'FIXED30-PRIME' AND status = 'ACTIVE';
```

Returns: **16 mortgages, average rate ≈ 5.85%**.

> **Heads-up on variance.** With the factory NL2SQL prompt the model sometimes punts and asks you for the column names instead of discovering them itself. Both behaviors are correct for a deliberately conservative default. If you want this act to behave the same way every time in front of a customer, run **Act 5b** *before* Act 3 — it tightens the workflow so the agent always chains schema-discovery → run-sql.

**Talking point:** "This is real-time — there's no extract job, no nightly sync, no stale dashboard. The model is querying the live database."

---

### Act 4 — Both together (the money shot)

**Settings:** Vector Search **on**, NL2SQL **on**.

**Prompt:**
> For our FIXED30-PRIME product: summarize the eligibility rules, then tell me how many of our current FIXED30-PRIME customers would no longer qualify under those rules.

**Expected behavior:** The combined-mode orchestrator routes to both tools, runs them in parallel, and synthesizes. The answer should:

1. Pull the FIXED30-PRIME thresholds from the underwriting policy (720 FICO, 80% LTV, 43% DTI, 2 months reserves)
2. Run a SQL query joining `MORTGAGES` and `CUSTOMERS` to count active FIXED30-PRIME holders whose current credit score is below 720
3. Answer: **4 customers** (Linh Nguyen, Yuki Tanaka, Noah Kim, Ravi Sharma) — and ideally name them

Neither capability alone can produce this answer. Vector Search alone doesn't know who current customers are; NL2SQL alone doesn't know what the policy threshold is.

**Talking point:** "This is the question that doesn't fit on a dashboard and doesn't fit in a chatbot. The two capabilities together produce an answer that requires both your documents and your data."

---

### Act 5 — Tune it for your bank (prompt engineering)

The factory prompts are deliberately generic — they behave safely on any database, any schema, any customer. **Tailoring them is how you make the optimizer feel like a system built for your bank**, not a generic chatbot.

Every prompt is editable in **Tools → 🎤 Prompts**, takes effect immediately, and is reversible with **Restore Default**.

Pick **one** for a tight 5-minute segment, or run all three for a deeper conversation. After each save, re-run the relevant earlier prompt to make the change visible.

#### 5b — Make NL2SQL deterministic and banker-friendly

**Open:** `optimizer_nl2sql-tools-default` (title: "NL2SQL Tools Prompt").

**Default reads:**

> You are an assistant connected to an Oracle database via SQLcl MCP Server.
> You can use any MCP tool that starts with "sqlcl_*". Only query data (no INSERT, UPDATE, DELETE, or DDL).
>
> Do exactly what the user asks. Call only the tool that matches their request.
> Do NOT call extra tools. When a tool returns a result, respond to the user immediately.
> Do NOT repeat or echo the tool call in your response. Just provide the result in plain text.
>
> Keep all actions read-only and safe.

**Edit to:**

```text
You are a senior SQL analyst connected to an Oracle database via the SQLcl MCP Server.
All available tools start with `sqlcl_*`. Only query data — never INSERT, UPDATE, DELETE, or DDL.
**Workflow for every question — do all steps autonomously, do not ask the user:**

1. If you are not already connected, call `sqlcl_connect` for the configured database.
2. If you do not already know the relevant tables, call `sqlcl_schema-information` to discover them. Read the table and column comments — they describe the meaning of each field, including allowed status values like `'ACTIVE'`, `'PAID_OFF'`, `'DEFAULTED'`.
3. Write the SQL query yourself. Do not ask the user for column names, table names, or allowed values — discover them from the schema.
4. Call `sqlcl_run-sql` to execute it.
5. Return the result in plain language.

**Never ask the user clarifying questions about the schema.** If a table or column you need is missing, say so plainly and stop — but only after you have actually checked the schema yourself.

**Formatting:**
- Always include the SQL you ran in a fenced code block at the end, under the heading "Query".
- Format dollar amounts with a leading "$" and thousands separators ($1,234,567.00). Format percentages to two decimals with a "%" suffix.
- Unless the user explicitly asks for historical, paid-off, or defaulted loans, restrict mortgage queries to `status = 'ACTIVE'`.

Keep all actions read-only and safe.
```

**Re-run Act 3's prompt.** The agent now reliably chains `connect → schema-information → run-sql`, returns the answer with the SQL appended, and formats the dollars and percentages.

**Talking point:** "The factory default is intentionally conservative — it won't go exploring your schema on its own. Two minutes of prompt editing teaches it your conventions: chain the discovery, default to active loans, show the SQL. That's how you go from coin-flip reliability to demo-grade reliability without writing any code."

---

#### 5c — Give the LLM-only mode a bank persona

**Open:** `optimizer_basic-default` (title: "Basic Prompt").

**Default reads:**

> You are a friendly, helpful assistant.

**Edit to:**

> You are a senior mortgage specialist at First National Bank. Answer the customer's question helpfully and in plain language. Cite specific product names, eligibility rules, and rates when relevant.

**Re-run Act 1's prompt.** The model now *tries* to be a bank specialist — it may invent product names, fabricate rates, or hedge nervously. This makes the "good failure" more pointed: the model wants to help and clearly cannot, which sharpens why steps 2–4 are necessary.

**Talking point:** "Persona alone doesn't get you there. The model is willing — it just doesn't know who *you* are. That's what the data and the documents solve."

---

#### Cleanup

After the demo, click **Restore Default** on each prompt you edited so the next demo starts fresh. Customizations are stored separately from the factory prompts, so reverting is non-destructive.

---

## More questions to try

Variations on each act, organized by what they demonstrate. Pick based on what your audience cares about — exec, risk, compliance, customer-experience.

### Vector Search variations (Act 2)

| Prompt | Why ask it |
|---|---|
| "What hardship programs do we offer if a customer loses their job?" | Pulls a specific section from the FAQ — empathy / customer-experience angle. |
| "Do we charge a prepayment penalty?" | *Nuanced* answer (varies by product). Shows the model handling conditional information, not just lookup. |
| "What are the reserve requirements for a jumbo loan?" | Cross-section: answer is in two places (catalog + policy). Shows retrieval pulling both. |
| "What happens to my monthly payment when property taxes go up?" | Purely FAQ. Shows the bot in a customer-facing voice. |

### NL2SQL variations (Act 3)

| Prompt | Why ask it |
|---|---|
| "What's our total active mortgage portfolio principal?" | Single big number. Great for execs. |
| "What's the average loan size for each product?" | `GROUP BY product_code`. |
| "Which state has the largest concentration of our mortgages?" | `GROUP BY state`. CA wins. |
| "Show me any mortgages currently in default." | Returns one row (Benjamin Cohen, JUMBO15-PRIME). Vivid — real name, real risk signal. |
| "How many customers have more than one mortgage with us?" | Needs `HAVING COUNT > 1`. Tests the model on something less obvious. |

### Combined-mode variations (Act 4 — the money shots)

| Prompt | Why ask it |
|---|---|
| "Are any of our active JUMBO15-PRIME customers below the credit-score floor for that product?" | Mirror of Act 4 but the answer is **zero**. "Our jumbo book is clean — and we know that in one question, not a quarterly audit." |
| "Which of our active mortgages would qualify for a refinance under our own rule-of-thumb (rate at least 0.75% below current base rate)?" | Pulls the refi heuristic from the FAQ + filters mortgages by rate vs. base rate. Operational use, not just compliance. |
| "For each product, how many active customers currently violate any underwriting threshold (credit, LTV, or reserves)?" | Stress test — pulls every threshold from the policy and applies them across the book. If the model nails this, the audience is sold. |
| "How much total principal is held by customers whose current credit score is below the policy floor for their product?" | Risk framing — converts the Act 4 finding into dollars. Great for CRO / risk officers. |

### Improv moment (always lands)

After Acts 1–4, before Act 5: **"What would you like to ask it?"** Open the floor. Bank execs love this because they get to test it on their own questions, and they always come up with something interesting. Keep a notepad of what they ask — those become the next demo's scripted prompts.

### One "intellectually honest" question

**"What was our origination volume last quarter?"** — the `PAYMENTS` table is sparse and there's no `originations` aggregate. The right answer is either "I can compute it from `MORTGAGES.origination_date`" (if the model is sharp) or "the data isn't structured that way." Useful for showing the system isn't pretending to know more than it does.

---

## Troubleshooting

- **Act 2 cites nothing / says "no relevant sources":** the vector store is empty or the embedding model differs from the one used at retrieval time. Re-embed with the same model that's selected in **Configuration → Models**.
- **Act 3 hangs or refuses to query:** SQLcl MCP isn't reachable or the DB connection alias has the wrong name. Confirm at **Configuration → Databases** that the test connection passes.
- **Act 3 gives different answers each run, or asks you to clarify the schema:** that's the variance described in the heads-up above. Apply Act 5b's prompt — it collapses the variance.
- **Act 4 answers from only one tool:** the classifier picked one path. Re-phrase to make the dual-source nature explicit (the prompt above does this with "summarize the rules, then tell me how many"). If using the on-prem Ollama fallback, this is more likely — the local model has weaker tool-use.
- **Act 4 returns the wrong count:** confirm the seed data loaded fully — re-run the verification queries in `PREREQ.md` step 7.

---

## Resetting between runs

To re-run from scratch:

```sql
-- In the schema with the vector store
DROP TABLE MORTGAGE_DOCS PURGE;
```

Then re-run `schema.sql` and re-embed the corpus (`PREREQ.md` steps 4 and 6). If you customized any prompts in Act 5, click **Restore Default** on each one.
