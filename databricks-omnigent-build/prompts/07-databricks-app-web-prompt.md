# Prompt 07 — Databricks App web dashboard

> Before anything else, read `../context/00-shared-context.md` in full — it holds the constraints this prompt assumes (the architectural boundary, audit fields, tech stack). If this prompt touches the sync API surface, also read `../context/08-api-contract.md`.


Depends on prompts 05 and 06. Run this as the matching Omnigent agent
from `../agents/`, in the same project.

---

Build the web review dashboard as a Databricks App, per the shared context (`../context/00-shared-context.md`).
This is where a scientist can pick up a session started on the
handheld, and where the study director reviews and approves flagged
records.

Build:
- A session view that calls `GET /v1/session/{session_id}` (prompt 06)
  and renders: the raw captured events in chronological order, each
  clearly tagged with its `source_flag` (on-device heuristic vs.
  unflagged) and its `capture_ts` vs. `sync_ts` — the gap between
  those two timestamps should be visible, not hidden, since that's
  part of the audit story.
- The agent's findings and full tool-call trace (Genie query text, UC
  function calls and results) rendered alongside the raw events, so
  the reviewer can see both what was captured and what the agent
  concluded from it — without the two being visually conflated.
- A review queue view listing sessions/records with agent findings
  pending approval.
- An approval action that, when triggered by an authorized reviewer,
  calls through to the agent's approval path from prompt 05 (which
  then calls `promote_approved_record`) — make sure this action is
  restricted to the study-director role, not available to whoever's
  logged in.
- Identity/auth wired to the same SSO used elsewhere in this system,
  so a scientist opening this on a laptop after using the handheld
  sees themselves as the same operator, not a different identity.
- A basic test pass: mock the API layer to verify the UI renders the
  on-device-heuristic vs. agent-confirmed distinction correctly, and a
  manual test plan for the approval flow end to end against a real
  test session.
