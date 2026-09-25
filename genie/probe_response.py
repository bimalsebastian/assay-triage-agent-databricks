"""Probe the Genie One MCP response structure — dump EVERYTHING, raw.

Purpose: find out whether Genie One exposes any "thought process" (generated
SQL, query descriptions, intermediate reasoning/attachments/items) beyond the
final markdown answer, so the app can surface it. This dumps the full raw
JSON-RPC payloads rather than the app's parsed subset.

Env: WORKSPACE_HOST, GENIE_BEARER (SP or U2M OAuth token).
Usage: python probe_response.py "Which compounds are flagged, and do any correlate clinically?"
"""
import json
import os
import sys
import time
import urllib.request

HOST = os.environ["WORKSPACE_HOST"].rstrip("/")
BEARER = os.environ["GENIE_BEARER"]
URL = f"{HOST}/api/2.0/mcp/genie"
PROTO = "2025-06-18"
_rid = 0


def rpc(method, params=None, notification=False):
    global _rid
    _rid += 1
    body = {"jsonrpc": "2.0", "method": method}
    if not notification:
        body["id"] = _rid
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST")
    req.add_header("Authorization", f"Bearer {BEARER}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")
    req.add_header("MCP-Protocol-Version", PROTO)
    with urllib.request.urlopen(req) as r:
        raw = r.read().decode()
    if notification or not raw.strip():
        return None
    if raw.lstrip().startswith("{"):
        return json.loads(raw)
    for line in raw.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return None


def dump(label, obj):
    print(f"\n{'='*70}\n{label}\n{'='*70}")
    print(json.dumps(obj, indent=2, default=str))


def call_tool(name, arguments):
    resp = rpc("tools/call", {"name": name, "arguments": arguments})
    result = (resp or {}).get("result", {})
    sc = result.get("structuredContent")
    if sc is not None:
        return sc, result
    for block in result.get("content", []) or []:
        if block.get("type") == "text":
            try:
                return json.loads(block["text"]), result
            except (ValueError, KeyError):
                continue
    return {}, result


def main():
    question = sys.argv[1] if len(sys.argv) > 1 else \
        "Which compounds are flagged, and do any correlate with a clinical signal?"

    rpc("initialize", {"protocolVersion": PROTO, "capabilities": {},
                       "clientInfo": {"name": "probe", "version": "1.0"}})
    rpc("notifications/initialized", notification=True)

    # 1. Full tool catalog + input schemas — reveals every tool + arg.
    dump("tools/list — full tool schemas", rpc("tools/list", {}))

    # 2. genie_ask — full raw result envelope.
    ask_sc, ask_raw = call_tool("genie_ask", {"question": question})
    dump("genie_ask — full result envelope (incl content blocks)", ask_raw)
    conv = ask_sc.get("conversation_id")
    resp = ask_sc.get("response_id")
    print(f"\n[conv={conv} resp={resp}]")

    # 3. Poll to completion, dumping the FULL structuredContent each time so we
    #    can see any evolving reasoning / attachments / items.
    status = (ask_sc.get("status") or "").lower()
    last_sc = ask_sc
    for i in range(80):
        if status in ("completed", "incomplete", "failed", "cancelled"):
            break
        time.sleep(2.5)
        last_sc, poll_raw = call_tool(
            "genie_poll_response",
            {"conversation_id": conv, "response_id": resp})
        status = (last_sc.get("status") or "").lower()
        if i < 2 or status in ("completed", "incomplete", "failed", "cancelled"):
            dump(f"genie_poll_response #{i} (status={status}) — full structuredContent", last_sc)

    # 4. Enumerate every key at the top level and any nested list-of-dicts, so
    #    hidden reasoning fields (attachments/items/steps/description) surface.
    print(f"\n{'='*70}\nTOP-LEVEL KEYS of final poll structuredContent\n{'='*70}")
    print(sorted(last_sc.keys()) if isinstance(last_sc, dict) else type(last_sc))

    # 5. If the response references query items, pull one via genie_get_query_result.
    for key in ("attachments", "items", "query_results", "queryAttachments"):
        items = last_sc.get(key) if isinstance(last_sc, dict) else None
        if isinstance(items, list) and items:
            print(f"\n[found list under '{key}' with {len(items)} item(s)]")
            item_id = (items[0].get("id") or items[0].get("attachment_id")
                       or items[0].get("item_id")) if isinstance(items[0], dict) else None
            if item_id:
                qr, qr_raw = call_tool("genie_get_query_result",
                                       {"conversation_id": conv, "response_id": resp,
                                        "item_id": item_id})
                dump(f"genie_get_query_result(item_id={item_id})", qr_raw)
            break


if __name__ == "__main__":
    main()
