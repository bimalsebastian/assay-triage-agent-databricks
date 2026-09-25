"""Probe whether the Genie MCP server exposes the MCP Apps interactive View
(view_ask + ui://genie/mcp-app.html) when we advertise MCP Apps capability.

This is reconnaissance for building an MCP Apps HOST inside our Databricks App.
It advertises the io.modelcontextprotocol/ui extension in initialize, then:
  1. tools/list      -> is view_ask present? what is _meta.ui.resourceUri?
  2. resources/list  -> what ui:// resources exist?
  3. resources/read  -> fetch the widget HTML (ui://genie/mcp-app.html)
  4. tools/call view_ask -> what does the tool result envelope look like?

Env: WORKSPACE_HOST, GENIE_BEARER (user/U2M token — OBO-shaped identity).
"""
import json
import os
import sys
import urllib.request

HOST = os.environ["WORKSPACE_HOST"].rstrip("/")
BEARER = os.environ["GENIE_BEARER"]
# Endpoint override: the per-workspace MCP (/api/2.0/mcp/genie) vs the managed
# Genie One MCP the docs tie to MCP Apps (/ai-gateway/mcp-services/...).
URL = os.environ.get("GENIE_MCP_URL") or f"{HOST}/api/2.0/mcp/genie"
print(f"[probing endpoint: {URL}]")
PROTO = "2025-06-18"
_rid = 0

# Advertise MCP Apps (io.modelcontextprotocol/ui) so the server offers view_ask.
CAPS = {"extensions": {"io.modelcontextprotocol/ui": {
    "mimeTypes": ["text/html;profile=mcp-app"]}}}


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
    if os.environ.get("UA"):
        req.add_header("User-Agent", os.environ["UA"])
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code, "_body": e.read().decode()[:600]}
    if notification or not raw.strip():
        return None
    if raw.lstrip().startswith("{"):
        return json.loads(raw)
    for line in raw.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return None


def dump(label, obj, cap=4000):
    print(f"\n{'='*70}\n{label}\n{'='*70}")
    s = json.dumps(obj, indent=2, default=str)
    print(s[:cap] + (f"\n… [truncated {len(s)-cap} chars]" if len(s) > cap else ""))


def main():
    cname = os.environ.get("CLIENT_NAME", "lead-opt-app-host")
    init = rpc("initialize", {"protocolVersion": PROTO, "capabilities": CAPS,
                              "clientInfo": {"name": cname, "version": "1.0"}})
    dump("initialize result (server capabilities / extensions echoed?)",
         (init or {}).get("result", init))
    rpc("notifications/initialized", notification=True)

    tools = rpc("tools/list", {})
    tool_list = (tools or {}).get("result", {}).get("tools", [])
    print(f"\n[tools offered: {[t.get('name') for t in tool_list]}]")
    for t in tool_list:
        if t.get("name") in ("view_ask", "genie_ask"):
            dump(f"tool '{t.get('name')}' (note _meta.ui.resourceUri)",
                 {"name": t.get("name"), "_meta": t.get("_meta"),
                  "annotations": t.get("annotations"),
                  "inputSchema_keys": list((t.get("inputSchema") or {}).get("properties", {}).keys())})

    res = rpc("resources/list", {})
    dump("resources/list", (res or {}).get("result", res))

    for uri in ("ui://genie/mcp-app.html", "ui://genie/mcp_app.html"):
        rd = rpc("resources/read", {"uri": uri})
        result = (rd or {}).get("result") if isinstance(rd, dict) else None
        if result and result.get("contents"):
            c = result["contents"][0]
            body = c.get("text") or c.get("blob") or ""
            print(f"\n{'='*70}\nresources/read {uri}\n{'='*70}")
            print(f"mimeType: {c.get('mimeType')}  | body length: {len(body)}")
            print("--- widget HTML head (first 1500 chars) ---")
            print(body[:1500])
            break
        else:
            dump(f"resources/read {uri} (no contents / error)", rd, cap=800)

    if any(t.get("name") == "view_ask" for t in tool_list):
        va = rpc("tools/call", {"name": "view_ask",
                                "arguments": {"question": "Which compounds are flagged?"}})
        dump("tools/call view_ask — full result envelope (_meta, structuredContent, content)",
             (va or {}).get("result", va))
    else:
        print("\n[view_ask NOT offered — server did not upgrade to the MCP Apps View]")


if __name__ == "__main__":
    import urllib.error
    main()
