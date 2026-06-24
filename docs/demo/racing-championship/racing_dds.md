<!--
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

spell-checker: ignore deepsec multiselect NL2SQL relref sqlplus Snetterton standings tnsadmin
-->

# Racing Championship — Deep Data Security Runbook

This runbook extends the [Racing Championship use-case](https://oracle.github.io/ai-optimizer/use-case/racing-championship/)
with [Oracle Deep Data Security](https://oracle.github.io/ai-optimizer/client/tools/deepsec/) (DDS). You will
add a row- and column-level access policy to the racing schema **from the AI Optimizer UI**, then confirm that the
policy is enforced — including on the **NL2SQL** agent, which sees only the data the policy allows with no
application-side changes.

It is a hands-on companion to the published docs, written to be copy-paste runnable during a demo. It does **not**
replace the use-case; load the racing schema first, then come here.

> **Why this is a good DDS demo.** The racing schema has obviously "sensitive" attributes — a driver's
> `skill_profile` (scouting notes) and per-team data — so masking a column and filtering rows produces a visible,
> believable before/after. Because DDS enforces inside the database, the same policy that protects a SQL query also
> protects the chatbot's NL2SQL answers.

---

## What you'll build

A single scenario you can demo in a few minutes:

| Object | Name (suggested) | Purpose |
|--------|------------------|---------|
| Data role | `RACING_ANALYST` | The principal the policy authorizes. |
| Data grant | `DG_DRIVERS_ANALYST` | On `DRIVERS`: `SELECT` on **all columns except `SKILL_PROFILE`** (column masking), filtered to a single team with a **row predicate** (`team_id = 1`). |
| End user | `SCOUT1` | A governed identity you connect as to observe the policy. |

Net effect: an analyst connecting as `SCOUT1` sees only Team 1's drivers, and never sees `SKILL_PROFILE`. The schema
owner still sees everything (owners are not subject to their own data grants — that is exactly why you test as the
end user).

---

## Prerequisites

1. **Oracle AI Database 26ai.** DDS is only available in 26ai. If the connected database does not support it, the
   **Deep Data Security** tab shows a *"not available"* notice instead of the management UI.
2. **The racing schema is loaded.** Complete *Setup → Load the schema* from the
   [use-case](https://oracle.github.io/ai-optimizer/use-case/racing-championship/) so `DRIVERS`, `RACE_RESULTS`,
   etc. exist in the AI Optimizer's configured database user (referred to below as `<SCHEMA>`).
3. **DDS privileges on `<SCHEMA>`.** The configured user needs the optional DDS privileges from the
   [Database Configuration](https://oracle.github.io/ai-optimizer/client/configuration/databases/) docs. As a DBA:

   ```sql
   GRANT CREATE DATA ROLE TO "<SCHEMA>";
   GRANT DROP DATA ROLE TO "<SCHEMA>";
   GRANT CREATE END USER TO "<SCHEMA>";
   GRANT DROP END USER TO "<SCHEMA>";
   GRANT CREATE DATA GRANT TO "<SCHEMA>";
   GRANT ADMINISTER ANY DATA GRANT TO "<SCHEMA>";
   GRANT CREATE END USER CONTEXT TO "<SCHEMA>";
   GRANT CREATE END USER SECURITY CONTEXT TO "<SCHEMA>";
   -- Assign locally-managed data roles to end users (Part 4)
   GRANT GRANT ANY DATA ROLE TO "<SCHEMA>";
   -- Read access so the tool can list data roles, role grants, and end users
   GRANT SELECT ON SYS.DBA_DATA_ROLES TO "<SCHEMA>";
   GRANT SELECT ON SYS.DBA_DATA_ROLE_GRANTS TO "<SCHEMA>";
   GRANT SELECT ON SYS.DBA_END_USERS TO "<SCHEMA>";
   ```

   The tool reads what the user can do and disables any action the user is not privileged for, so granting a subset
   still works — you just see fewer enabled buttons.

---

## Part 1 — Confirm DDS is available (UI)

1. In the AI Optimizer, open **Tools → 🔒 Deep Data Security**.
2. The page renders three stacked sections: **Data Roles**, **End Users**, and **Data Grants**.
   - If you instead see *"Deep Data Security is not available on the **<database>** database. It requires Oracle AI
     Database 26ai,"* your database build does not support DDS — switch the **Configuration → Database** connection
     to a 26ai database.
   - If an action is disabled, the page shows an inline hint with the exact `GRANT … TO <user>;` it needs (for
     example, *"Assigning data roles requires: `GRANT ANY DATA ROLE to <user>;`"*). A missing privilege disables only
     its related action; the rest of the demo still works. Revisit the grants in Prerequisites.

---

## Part 2 — Create the data role (UI)

1. Go to the **Data Roles** section.
2. Click **Create Data Role**. In the dialog, set:
   - **Data role name:** `RACING_ANALYST`
   - **Mapped to:** leave blank (a local role; you would fill this in only to map to an external identity-provider
     application role).
3. Click **Create**.
4. The new role appears in the list with **Enabled by Default = Yes**. Leave it enabled by default: for a
   locally-managed role this means that *once the role is granted to an end user* (Part 4) it is active in that
   user's session without an explicit `SET` — it does **not** grant the role to anyone on its own.

---

## Part 3 — Create the data grant: column + row policy (UI)

This is where the actual access policy is written.

1. Go to the **Data Grants** section.
2. Fill in the grant builder:
   - **Data grant name:** `DG_DRIVERS_ANALYST`
   - **Object (table/view):** `DRIVERS`
   - **Privileges:** `SELECT`
   - **Columns:** choose **All columns except**, then in the column picker select `SKILL_PROFILE`.
     This authorizes every column on `DRIVERS` *except* `SKILL_PROFILE`, so that column is masked for the grantee.
   - **Row predicate:** `team_id = 1`
     A SQL `WHERE` expression evaluated per row; only Team 1's drivers are visible.
   - **Grant to data role:** `RACING_ANALYST`
3. Review the generated statement shown in the preview block. It should read close to:

   ```sql
   CREATE DATA GRANT DG_DRIVERS_ANALYST
     AS SELECT (ALL COLUMNS EXCEPT "SKILL_PROFILE") ON DRIVERS
     WHERE team_id = 1
     TO RACING_ANALYST;
   ```

   The server builds and runs the authoritative statement; the preview is for your review.
4. Click **Create data grant**. It now appears (expanded per column) in the data-grants list.

> **Tip — pick columns that show well.** `SKILL_PROFILE` is the scouting attribute, so masking it is the clearest
> "before/after." `VEHICLE_SETUP` and `DRIVING_STYLE` are good secondary choices.

---

## Part 4 — Create the end user (UI)

1. Go to the **End Users** section.
2. Click **Create End User**. In the dialog, set:
   - **End user name:** `SCOUT1`
   - **Schema (for name resolution):** leave the default (`<SCHEMA>`, the connected user). This is the schema that
     `SCOUT1`'s unqualified object names resolve against.
   - **No password field:** the end user is provisioned server-side with the **same password as the connected
     database user** (`<SCHEMA>`). You will use that password when you connect as `SCOUT1` in Part 5.
   - **Assigned data roles:** select `RACING_ANALYST`. This is the step that actually grants the role to the end
     user (`GRANT DATA ROLE RACING_ANALYST TO SCOUT1`) and requires `GRANT ANY DATA ROLE` from Prerequisites. If the
     multiselect is disabled, you are missing that privilege.
3. Click **Create**. `SCOUT1` appears in the list with its account status.

Because `RACING_ANALYST` was granted to `SCOUT1` and is enabled by default, `SCOUT1` is governed by
`DG_DRIVERS_ANALYST` as soon as it connects. (Granting the role is required — a locally-managed role is not picked up
automatically just because it is enabled by default. You can revisit the assignment any time via **Edit** next to the
end user.)

---

## Part 5 — Test that the policy is enforced

The schema owner (`<SCHEMA>`) is **not** subject to its own data grants, so you must test as `SCOUT1`. Do the
authoritative SQL check first, then optionally show it end-to-end through the chatbot.

### 5a — Ground truth in SQL (authoritative)

Connect **as the owner** and look at Driver 1's row in full:

```sql
-- As <SCHEMA>: owner bypasses data grants, sees everything
SELECT driver_code, team_id, skill_profile
FROM   drivers
WHERE  driver_id <= 3
ORDER  BY driver_id;
```

Now connect **as the end user** and run the equivalent query against the owner's table:

```sql
-- As SCOUT1 (for example: sqlplus 'SCOUT1/<password>@<dsn>')
SELECT driver_code, team_id, skill_profile
FROM   <SCHEMA>.drivers
ORDER  BY driver_id;
```

**What to look for:**

- Only **Team 1** drivers are returned (the `team_id = 1` row predicate).
- `SKILL_PROFILE` comes back **masked (NULL)** for those rows (the `ALL COLUMNS EXCEPT` column policy).
- The owner query, by contrast, returned every team and the real `SKILL_PROFILE` text.

That difference, owner vs. end user against the *same* table, is the policy working.

### 5b — Through the AI Optimizer (NL2SQL / ChatBot)

This shows the headline DDS claim: the agent inherits the policy, with no prompt or app changes.

1. In **Configuration → Database**, select **Add New…** and create a second connection that authenticates as the end
   user:
   - **Alias:** `RACING_SCOUT`
   - **Username:** `SCOUT1`
   - **Password:** the `<SCHEMA>` password — `SCOUT1` was provisioned with the connected database user's password
     (Part 4)
   - **DSN:** the same database as `<SCHEMA>`
   - Save, then select `RACING_SCOUT` as the active database.
2. Make sure the **NL2SQL** tool is on (and, if you imported `prompts.json`, that the racing NL2SQL prompt is
   active).
3. In the **ChatBot**, ask:

   ```text
   List the drivers and their skill profiles.

   How many drivers are there in total, and which teams are they on?
   ```

   **What to look for:** the agent's answers cover only Team 1's drivers, and skill-profile values come back empty or
   "not available" — the same masking and row filter you saw in SQL, now enforced on the agent's generated query.
4. Switch the active database back to `<SCHEMA>` and ask the same questions. The agent now sees all teams and the
   real skill profiles — the policy applies to the *connection*, not the application.

> If the agent reports it cannot find `DRIVERS` while connected as `SCOUT1`, the end user cannot resolve the owner's
> table by an unqualified name. See *Notes & caveats* — the SQL check in 5a (which qualifies `<SCHEMA>.drivers`) is
> the reliable verification, and a private synonym makes the NL2SQL path resolve cleanly.

---

## Part 6 — More policies to try

Each is built the same way in the **Data Grants** section; only the highlighted fields change.

| Goal | Object | Privileges | Columns | Row predicate |
|------|--------|-----------|---------|---------------|
| Hide penalties from analysts | `RACE_RESULTS` | `SELECT` | All columns except `PENALTIES` | *(none)* |
| Show one team's results only | `RACE_RESULTS` | `SELECT` | All columns | `driver_id IN (SELECT driver_id FROM <SCHEMA>.drivers WHERE team_id = 1)` |
| Expose only published team points | `TEAM_RACE_POINTS` | `SELECT` | All columns except `RACE_CONTROL_NOTE` | `publication_status = 'PUBLISHED'` |
| Read-only on a narrow column set | `DRIVERS` | `SELECT` | Specific columns: `DRIVER_CODE`, `TEAM_ID` | *(none)* |

Re-run the Part 5 checks (as `SCOUT1`) after each to see the effect. The "published team points" policy pairs nicely
with the use-case's Final Reveal: an analyst sees a team's points only once `publication_status` flips to published.

---

## Cleanup

Remove the demo objects from the UI, in dependency order (drop the grant before the role it targets):

1. **Data Grants** section → **Drop** `DG_DRIVERS_ANALYST` from its row.
2. **End Users** section → **Edit** next to `SCOUT1` → **Delete**.
3. **Data Roles** section → **Edit** next to `RACING_ANALYST` → **Delete**.

If you added the `RACING_SCOUT` database connection, you can remove it from **Configuration → Database**. The racing
schema itself is untouched — DDS objects are separate from the demo tables.

---

## Notes & caveats

- **Owners bypass their own data grants.** The user that owns `DRIVERS` always sees full data, so enforcement is only
  observable when you connect as an end user (or another governed identity). This is the single most common point of
  confusion in a DDS demo.
- **Granting vs. enabled-by-default.** A locally-managed data role must be **granted** to the end user — that is the
  **Assigned data roles** step in Part 4 (`GRANT DATA ROLE … TO SCOUT1`). `enabled_by_default` is a separate property:
  it only controls whether an *already-granted* role is active in the session without an explicit `SET`. A role that is
  enabled by default but never granted reaches no one. Mapping a role to an external application role (the **Mapped
  to** field) is the alternative, identity-provider-driven path and does not use end-user grants.
- **End user resolving owner objects.** End users access the data owner's tables. The SQL check in 5a qualifies the
  name (`<SCHEMA>.drivers`); for the NL2SQL agent to use an unqualified `DRIVERS`, create a private synonym for
  `SCOUT1` (`CREATE SYNONYM ... FOR <SCHEMA>.drivers`) or keep the racing NL2SQL prompt's schema qualification.
- **Masking representation.** Column-level `SELECT (ALL COLUMNS EXCEPT …)` returns the excluded column as NULL for the
  grantee; row predicates remove non-matching rows entirely. Exact behavior follows Oracle AI Database 26ai.
- **Predicates are policy text.** The row predicate is free-form SQL run with the grantee's privileges and capped in
  length by the server; keep it to columns on the target object (or subqueries the grantee can read).
- **This document has not been executed end-to-end against a live 26ai database in this repository.** The UI steps,
  field names, and generated DDL are taken from the tool's implementation; validate the masking/row-filter output in
  your environment (step 5a) before relying on it for a live demo.

---

## Troubleshooting

- **Deep Data Security shows "not available":** the active database is not 26ai. Switch connections in
  **Configuration → Database**.
- **Buttons / fields are greyed out:** the configured user is missing a DDS privilege. The disabled control shows the
  exact `GRANT … TO <user>;` it needs (e.g. the **Assigned data roles** multiselect needs `GRANT ANY DATA ROLE`).
  Grant it (Prerequisites) and reload.
- **`SCOUT1` sees all rows / unmasked columns:** the data role is not reaching the end user. Check that
  `RACING_ANALYST` was **granted to `SCOUT1`** (Part 4 → **Assigned data roles**, or **Edit** next to the end user),
  that `DG_DRIVERS_ANALYST` was granted **to `RACING_ANALYST`**, and that you are actually connected as `SCOUT1` (not
  the owner).
- **`SCOUT1` sees no rows at all:** DDS is deny-by-default — without a matching data grant the end user sees nothing.
  Confirm the grant exists and that your row predicate matches real data (Team 1 has drivers in the seed).
- **NL2SQL can't find the table as `SCOUT1`:** add a private synonym for the owner's tables, or verify enforcement
  with the SQL check in 5a instead.
