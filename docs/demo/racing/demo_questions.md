# F1 Racing AI Demo Questions

Use these questions during the live hands-on demo. Each participant should replace `<driver number>` with their assigned driver number, for example `Driver 1`, `Driver 17`, or `Driver 73`.

The demo flow is designed to show the difference between an ungrounded LLM answer, structured NL2SQL grounding, unstructured RAG grounding, and a final combined NL2SQL plus RAG answer.

## Step 1: Pure LLM Only

Purpose: show that the model does not know the synthetic demo data unless it is connected to a source.

Ask:
I am Driver `<driver number>`...
- What team am I on?
- How many championship points do I have?
- What should I improve before the next race?

Expected teaching point:

The model may answer generally, refuse to guess, or hallucinate. It has no reliable access to the synthetic driver assignment data yet.

## Step 2: NL2SQL On

Purpose: show that structured questions can now be answered from Oracle tables and views.

Ask:

I am Driver `<driver number>`...
- What is my driving style?
- What vehicle setup and simulator rig am I assigned to?
- Which team am I on?
- What is my team engineering focus?
- How many points do I have before the finale?
- What was my best finish?
- What was my fastest lap and in which race?
- Did I have any incidents?
- How many pit stops did I make?
- Compare me with Driver `<another driver number>` on total points, best finish, average lap time, and incidents.
- Which drivers have the same driving style as me?
- Which team is leading before Round 6?

Expected teaching point:

NL2SQL can translate natural language into SQL and retrieve exact structured facts from the database. It should not invent final Round 6 results because those results are not in the structured tables.

## Step 3: RAG On

Purpose: show that unstructured documents can answer briefing, coaching, and narrative questions.

Before this step, participants should embed the driver document for their assigned driver from `driver_documents/`, for example `driver_documents/driver_001.md` for Driver 1.

Ask:
I am Driver `<driver number>`...
- What team am I on?
- Summarize my driver briefing.
- What did my coach say I should improve?
- What setup advice was given to me?
- What does my race debrief say?
- What risks or weaknesses are mentioned in my notes?
- Give me three practical focus areas for my next simulator session.

Expected teaching point:

RAG can retrieve and summarize relevant unstructured text, but by itself it may not reliably calculate standings, totals, rankings, or joins across structured tables.

## Step 4: NL2SQL And RAG Together

Purpose: show that the strongest answers combine structured database facts with retrieved documents.

Ask:

I am Driver `<driver number>`...
- Use my database results and my documents to summarize my season so far.
- Based on my points, incidents, and coaching notes, what should I focus on next?
- Which race should I review first, based on my worst structured result and my debrief notes?
- Did my structured performance match the feedback in my documents?
- Compare me with Driver `<another driver number>` using both database results and driver notes.

Expected teaching point:

The model can use NL2SQL for exact facts and RAG for explanations, context, and recommendations.

## Final Reveal: Winning Team

Purpose: show why both structured and unstructured grounding matter.

Before this step, embed `finale_results.md`. This Race Control Bulletin contains the final Round 6 team points, but it does not directly state the winning team.

Ask:

- Using the database team standings and the Round 6 Race Control Bulletin, which team won the championship? Show the pre-finale points, the Round 6 points, and the final total.
- Which teams were in contention before Round 6, and how did the Race Control Bulletin change the result?
- Why could NL2SQL alone not answer the final championship winner?
- Why could RAG alone not confidently answer the final championship winner?

Expected teaching point:

NL2SQL provides the pre-finale standings from structured tables. RAG provides the late-arriving Round 6 Race Control Bulletin. The final answer requires combining both sources.

## Useful Driver Identifier Guidance

Participants can refer to themselves naturally as:

- Driver `<driver number>`, for example `Driver 1`
- Driver code `Driver001`, `Driver017`, or `Driver073`

If a question fails because the driver number is ambiguous, ask again using the padded driver code.
