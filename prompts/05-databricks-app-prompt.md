# Prompt 05 — Databricks App dashboard

> Read `../CLAUDE.md` in full first. Depends on prompts 03 (Lakebase
> access layer) and 04 (Genie space).

---

Build the Databricks App that surfaces this to the business — the
piece a non-technical reviewer actually opens.

Build:

- A review-queue view reading from the Lakebase access layer (prompt
  03): each flagged compound, its reading, what it was compared
  against, and a "mark resolved" action wired to the resolve function
  from prompt 03.
- An inline "ask a question" box that sends a natural-language
  question to the Genie space (prompt 04) and shows the answer —
  doesn't need to be fancy, a text input and a response panel is
  enough to demonstrate the Genie integration is live from the app,
  not just from the Genie UI directly.
- Basic auth wired to workspace SSO, since this is what makes it "a
  business app" rather than a notebook.
- A short manual test pass: resolve an item in the queue and confirm
  it disappears/updates; ask a Genie question from the app and confirm
  a real answer comes back.
- Confirm this ran for real: deploy the app, take the actual rendered
  queue content and a real Genie Q&A exchange from within the app, and
  commit both as text (the queue's row data, the Q&A text) in the
  repo — not a screenshot. This is the last piece of execution
  evidence the whole journey needs, since it's the end of the chain
  everything before it fed into.
