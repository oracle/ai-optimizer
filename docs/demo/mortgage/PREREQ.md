# Mortgage Demo — Prerequisites & Setup

Complete this one-time setup before running the demo. Once it's done, you can re-run the demo as many times as you like — only the **Resetting between runs** section in `README.md` is needed between runs.

---

## 1. System prerequisites

- Oracle Database 26ai reachable from the AI Optimizer host
- AI Optimizer server (`:8000`) and client (`:8501`) already running
- A schema-owner DB account with privileges to create tables and a vector store (the script in step 3 creates this for you)
- SQLcl 25.2+ installed if you plan to demo NL2SQL — the optimizer launches it as an MCP server

---

## 2. Pick an LLM and embedding model

The combined-mode prompt does classification → parallel sub-calls → synthesis, so the LLM needs solid tool-use. Pick one row:

| Scenario | LLM | Embedding |
|---|---|---|
| Hosted, fastest setup | OpenAI `gpt-4o` | OpenAI `text-embedding-3-small` |
| Oracle-native | OCI Generative AI — `cohere.command-r-plus` | OCI — `cohere.embed-english-v3.0` |
| Fully on-prem fallback | Ollama `llama3.1:8b` | Ollama `mxbai-embed-large` |

Configure the chosen models in the AI Optimizer client at **Configuration → Models**. Both must show as enabled before continuing.

---

## 3. Create the database user

Run as a privileged DBA account. Edit the constants at the top to suit your environment.

```sql
DECLARE
    c_user_name     CONSTANT VARCHAR2(30) := 'MORTGAGE';
    c_user_password dba_users.password%TYPE := 'MYSUPERSECRET';
    v_default_perm  database_properties.property_value%TYPE;
    v_default_temp  database_properties.property_value%TYPE;
    v_sql           VARCHAR2(500);
BEGIN
    SELECT property_value
    INTO v_default_perm
    FROM database_properties
    WHERE property_name = 'DEFAULT_PERMANENT_TABLESPACE';

    SELECT property_value
    INTO v_default_temp
    FROM database_properties
    WHERE property_name = 'DEFAULT_TEMP_TABLESPACE';

    v_sql := 'CREATE USER ' || DBMS_ASSERT.ENQUOTE_NAME(c_user_name, FALSE) ||
            ' IDENTIFIED BY "' || c_user_password || '" ' ||
            'DEFAULT TABLESPACE ' || v_default_perm || ' ' ||
            'TEMPORARY TABLESPACE ' || v_default_temp;
    EXECUTE IMMEDIATE v_sql;

    EXECUTE IMMEDIATE 'GRANT DB_DEVELOPER_ROLE TO ' ||
        DBMS_ASSERT.ENQUOTE_NAME(c_user_name, FALSE);
    EXECUTE IMMEDIATE 'ALTER USER ' ||
        DBMS_ASSERT.ENQUOTE_NAME(c_user_name, FALSE) || ' DEFAULT ROLE ALL';
    EXECUTE IMMEDIATE 'ALTER USER ' ||
        DBMS_ASSERT.ENQUOTE_NAME(c_user_name, FALSE) || ' QUOTA UNLIMITED ON DATA';
END;
/
```

---

## 4. Load the schema

Run `schema.sql` as the user you just created (e.g. `MORTGAGE`):

```bash
sql MORTGAGE/<password>@<dsn> @schema.sql
```

The script ends with two verification queries. Expected results:

- `FIXED30-PRIME, ACTIVE` → 16 rows
- The "4 customers" query → exactly four rows: Linh Nguyen 680, Yuki Tanaka 695, Noah Kim 705, Ravi Sharma 712

If those numbers don't match, **stop** and re-run the script — the combined-mode demo answer (Act 4) will be wrong otherwise.

---

## 5. Wire the database into the AI Optimizer

In the client at **Configuration → Databases**, add a connection alias (suggest `MORTGAGE`) pointing at the schema you just loaded. Click **Test Connection** — it must succeed before continuing.

---

## 6. Embed the corpus

In the client at **Tools → 📚 Split/Embed**:

1. Upload all three markdown files from `corpus/` (`01-product-catalog.md`, `02-underwriting-policy.md`, `03-customer-faq.md`)
2. Choose the embedding model from step 2
3. Use the default chunk size and overlap
4. Name the vector store table something memorable, e.g. `MORTGAGE_DOCS`
5. Click **Embed** and wait for completion

Verify a chunk count was reported — should be roughly 15–25 chunks across the three docs.

---

## 7. Pre-flight verification

Run these before the demo to confirm both data and embeddings are correct.

```sql
-- Should return 16
SELECT COUNT(*) FROM mortgages
WHERE product_code = 'FIXED30-PRIME' AND status = 'ACTIVE';

-- Should return exactly 4 rows
SELECT c.full_name, c.credit_score
FROM   mortgages m JOIN customers c ON c.customer_id = m.customer_id
WHERE  m.product_code = 'FIXED30-PRIME'
  AND  m.status       = 'ACTIVE'
  AND  c.credit_score < 720
ORDER  BY c.credit_score;
```

In the AI Optimizer, do a quick smoke test:

- **Act 1 prompt** with all tools off → generic answer (intended)
- **Act 2 prompt** with Vector Search on → cites the catalog/policy
- **Act 3 prompt** with NL2SQL on → returns 16 mortgages

If all three behave as expected, you're ready. Open `README.md` for the run-of-show.
