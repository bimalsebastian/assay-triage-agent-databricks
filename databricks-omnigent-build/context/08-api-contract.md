# API contract — Android client ↔ backend agent endpoint

> Shared verbatim with the Android builder's `07-api-contract.md`. If you edit this, copy the same edit back to them.

Shared source of truth between the Android builder and the
Databricks/backend builder. Change this together, not unilaterally —
both sides' prompts assume these shapes.

This describes the *shape* of the contract, not a finished OpenAPI
spec. Treat field names and paths below as a starting draft to
negotiate with the backend builder, not as already-fixed.

## POST /v1/sync

Called by the Android sync worker on connectivity restore. Batches
everything queued since the last successful sync.

Request body:
```json
{
  "device_id": "string",
  "operator_id": "string",
  "session_id": "uuid (client-generated)",
  "events": [
    {
      "event_id": "uuid (client-generated)",
      "type": "scan | observation",
      "sample_id": "string",
      "payload": "type-specific fields (barcode data, or observation text)",
      "capture_ts": "ISO 8601, set on-device at capture time",
      "source_flag": "on_device_heuristic | unflagged",
      "correction_of_event_id": "uuid | null"
    }
  ]
}
```

Response body:
```json
{
  "sync_ts": "ISO 8601, server time — authoritative, not device time",
  "accepted_event_ids": ["uuid", "..."],
  "rejected_events": [{"event_id": "uuid", "reason": "string"}],
  "session_state": {
    "session_id": "uuid",
    "status": "string",
    "agent_summary": "string | null — set once the agent has actually processed the batch, may be null immediately after sync",
    "last_updated_ts": "ISO 8601"
  }
}
```

Notes for the Android side: `session_state` in the response is what
gets cached locally and is what makes mobile→web continuity work — if
this is missing or stale, the web client won't see a consistent
picture. Don't set local `sync_ts` from anything other than the
server's value in this response.

Notes for the backend side: `source_flag` must be passed through
unmodified to wherever the web client reads it from — the web UI
needs to render on-device heuristic flags differently from
agent-confirmed ones, same distinction as the Android side.

## GET /v1/context-bundle?compound_ids=...

Called at the start of a shift (or manually) to refresh the local
heuristic's cached data. Scoped to a bounded list of compound IDs, not
a full-table pull.

Response body:
```json
{
  "bundle_ts": "ISO 8601 — when this snapshot was generated server-side",
  "compounds": [
    {
      "compound_id": "string",
      "recent_readings": [{"value": "number", "unit": "string", "ts": "ISO 8601"}],
      "threshold": "number | null"
    }
  ]
}
```

## GET /v1/session/{session_id}

Called by the web client to resume a session started or updated from
the Android app. Returns the same `session_state` shape as the sync
response, plus the full event list for that session so the web UI can
render the complete trail (agent tool calls, Genie queries, UC
function results) alongside the raw capture events.

## Open items to confirm with the backend builder before prompt 05

- Auth mechanism for these calls (expect OAuth token from the same
  identity provider used for SSO on both clients — confirm exact
  flow).
- Whether `/v1/sync` needs idempotency handling beyond
  `event_id`-based dedup (e.g. a retried batch after a timeout where
  the first attempt actually succeeded server-side).
- Pagination for `/v1/session/{session_id}` if event lists get long.
