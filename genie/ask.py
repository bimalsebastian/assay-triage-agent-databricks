"""Ask the Genie space a question via the Conversations API and print the answer.

Auth uses the bearer in env GENIE_BEARER (the service principal's OAuth token,
so queries run as the scoped SP, not personal credentials). Host in env
WORKSPACE_HOST, space id in env GENIE_SPACE_ID.

Prints the question, Genie's generated SQL (if any), its text answer, and a few
result rows.
"""
import json
import os
import sys
import time
import urllib.request

HOST = os.environ["WORKSPACE_HOST"].rstrip("/")
SPACE = os.environ["GENIE_SPACE_ID"]
BEARER = os.environ["GENIE_BEARER"]
BASE = f"{HOST}/api/2.0/genie/spaces/{SPACE}"


def _req(method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{HOST}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {BEARER}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode())


def ask(question: str) -> dict:
    start = _req("POST", f"/api/2.0/genie/spaces/{SPACE}/start-conversation",
                 {"content": question})
    conv = start.get("conversation_id") or start["conversation"]["id"]
    msg = start.get("message_id") or start["message"]["id"]

    # Poll until the message completes.
    for _ in range(60):
        m = _req("GET", f"/api/2.0/genie/spaces/{SPACE}/conversations/{conv}/messages/{msg}")
        status = m.get("status")
        if status in ("COMPLETED", "FAILED", "CANCELLED"):
            break
        time.sleep(3)

    out = {"question": question, "status": status, "text": None, "sql": None, "rows": None}
    for att in m.get("attachments", []) or []:
        if att.get("text"):
            out["text"] = att["text"].get("content")
        if att.get("query"):
            q = att["query"]
            out["sql"] = q.get("query")
            aid = att.get("attachment_id")
            try:
                qr = _req("GET", f"/api/2.0/genie/spaces/{SPACE}/conversations/{conv}"
                                 f"/messages/{msg}/attachments/{aid}/query-result")
                res = qr.get("statement_response", {}).get("result", {})
                out["rows"] = res.get("data_array")
            except Exception as e:  # noqa: BLE001
                out["rows"] = f"(result fetch error: {e})"
    return out


if __name__ == "__main__":
    r = ask(sys.argv[1])
    print(f"Q: {r['question']}")
    print(f"status: {r['status']}")
    if r["sql"]:
        print("generated SQL:\n  " + r["sql"].replace("\n", "\n  "))
    if r["rows"] is not None:
        preview = r["rows"][:6] if isinstance(r["rows"], list) else r["rows"]
        print(f"result rows (up to 6): {preview}")
    if r["text"]:
        print(f"answer: {r['text']}")
