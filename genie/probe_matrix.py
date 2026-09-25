"""Differential matrix probe: is `view_ask` gating a negotiation issue on our side,
or is the MCP App View simply not active on this workspace's server?

For each (endpoint x protocolVersion x extension-advertised? x mimeType) combo:
 - initialize, capture the echoed `capabilities.extensions`
 - tools/list, report whether `view_ask` appears and whether the tool set changed
 - report whether the server advertises the `resources` capability
If NO combination yields view_ask, the feature is off server-side (not our format).

Env: WORKSPACE_HOST, GENIE_BEARER.
"""
import json
import os
import urllib.error
import urllib.request

HOST = os.environ["WORKSPACE_HOST"].rstrip("/")
BEARER = os.environ["GENIE_BEARER"]
ENDPOINTS = ["/api/2.0/mcp/genie", "/ai-gateway/mcp-services/system.ai.genie_one_mcp"]
PROTOS = ["2025-06-18", "2025-11-05", "2024-11-05"]
MIMES = ["text/html;profile=mcp-app", "text/html+skybridge", "text/html"]


def rpc(url, proto, method, params=None, notification=False, rid=[0]):
    rid[0] += 1
    body = {"jsonrpc": "2.0", "method": method}
    if not notification:
        body["id"] = rid[0]
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    req.add_header("Authorization", f"Bearer {BEARER}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")
    req.add_header("MCP-Protocol-Version", proto)
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code}
    if notification or not raw.strip():
        return None
    if raw.lstrip().startswith("{"):
        return json.loads(raw)
    for line in raw.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return None


def run(url, proto, advertise, mime):
    caps = {}
    if advertise:
        caps = {"extensions": {"io.modelcontextprotocol/ui": {"mimeTypes": [mime]}}}
    init = rpc(url, proto, "initialize", {
        "protocolVersion": proto, "capabilities": caps,
        "clientInfo": {"name": "claude-desktop", "version": "1.0.0"}})
    if not init or "result" not in init:
        return f"init_failed({(init or {}).get('_http_error','?')})"
    res = init["result"]
    echoed = res.get("capabilities", {}).get("extensions", {})
    has_resources = "resources" in res.get("capabilities", {})
    rpc(url, proto, "notifications/initialized", notification=True)
    tl = rpc(url, proto, "tools/list", {})
    tools = [t.get("name") for t in (tl or {}).get("result", {}).get("tools", [])]
    view = "view_ask" in tools
    return (f"view_ask={'YES' if view else 'no ':<3} resources_cap={has_resources} "
            f"ext_echo={json.dumps(echoed)} tools={tools}")


def main():
    for ep in ENDPOINTS:
        url = HOST + ep
        print(f"\n{'#'*72}\n# {ep}\n{'#'*72}")
        # Baseline: no extension advertised.
        print(f"[no-ext  proto=2025-06-18] {run(url, '2025-06-18', False, '')}")
        # Matrix: extension advertised across protocols x mimeTypes.
        for proto in PROTOS:
            for mime in MIMES:
                print(f"[ext {mime:<26} proto={proto}] {run(url, proto, True, mime)}")


if __name__ == "__main__":
    main()
