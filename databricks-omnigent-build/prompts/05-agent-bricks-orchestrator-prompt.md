# Prompt 05 — Agent Bricks orchestrator

> Before anything else, read `../context/00-shared-context.md` in full — it holds the constraints this prompt assumes (the architectural boundary, audit fields, tech stack). If this prompt touches the sync API surface, also read `../context/08-api-contract.md`.


Depends on prompts 01–04. Run this as the matching Omnigent agent from
`../agents/`, in the same project.

---

Build the Agent Bricks custom agent that orchestrates Genie, the UC
functions, and Lakebase, per the shared context (`../context/00-shared-context.md`).

Build:
- Agent definition (MLflow-based, per Agent Bricks conventions) with
  three tools registered: the Genie space from prompt 03, the two UC
  functions from prompt 02, and the Lakebase access layer from prompt
  04 (read/write session and event state).
- A system prompt / instructions for the agent that encodes the
  behavior this whole system depends on: when it receives new events
  for a session, check prior history via Genie, run the ADMET check
  via the UC function if relevant, write its findings back to
  Lakebase against the session, and — critically — never overwrite or
  relabel an incoming `source_flag` of `on_device_heuristic`; its own
  findings are additive, not a replacement.
- Handling for the approval step: when the web app signals a human
  approval for a session/record, the agent (or the code path around
  it) calls `promote_approved_record` — and only then. Don't let any
  other code path call that UC function.
- Logging/tracing of every tool call the agent makes (Genie query
  text, UC function inputs and outputs, Lakebase reads/writes) in a
  form the web app can later render as the full audit trail — this is
  what the study director reviews before approving.
- Unit and integration tests: mock the three tools first to verify the
  orchestration logic in isolation, then a real integration test
  against the actual Genie space, UC functions, and a test Lakebase
  instance for at least one full "new event in → findings written
  back out" round trip.

Don't wire this into the sync API's HTTP layer yet — that's prompt 06.
This prompt is about the agent itself being correct and testable on
its own.
