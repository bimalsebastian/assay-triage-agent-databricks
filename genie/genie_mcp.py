"""Unified Genie client over the Databricks Managed MCP server.

ONE interface addresses ANY Genie space by id, so the app (and the CLI driver)
talk to the preclinical room and the separate scoped clinical room through the
same code path instead of two bespoke REST clients.

Managed Genie MCP contract (verified live against the workspace):
  endpoint : {host}/api/2.0/mcp/genie/{space_id}
  protocol : JSON-RPC 2.0 over HTTP (stateless; application/json responses)
  sequence : initialize -> notifications/initialized -> tools/call
  tools    : query_space_{space_id}(query[, conversation_id])
             poll_response_{space_id}(conversation_id, message_id)
  result   : result.structuredContent = {
                 content: {textAttachments:[...], queryAttachments:[
                     {query: <sql>, statement_response: {... result.data_array ...}}]},
                 conversationId, messageId, status }   # status: ASKING_AI -> COMPLETED

Auth is a bearer token supplied by a caller-provided token_provider() — the app
passes its service-principal OAuth token, the CLI passes a U2M token. The space's
own scope/grants still apply: the SP can only reach rooms it has CAN_RUN on, and
each room only exposes the tables it was scoped to (the clinical room is aggregate
-only), so this client changes the transport, not the governance surface.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

_TERMINAL = ("COMPLETED", "FAILED", "CANCELLED")


class GenieMCP:
    def __init__(self, host: str, token_provider, protocol_version: str = "2025-06-18"):
        self._host = host.rstrip("/")
        self._token_provider = token_provider
        self._protocol_version = protocol_version
        self._rid = 0

    # -- low-level JSON-RPC over the managed MCP endpoint ------------------
    def _rpc(self, space_id: str, method: str, params: dict | None = None,
             notification: bool = False):
        self._rid += 1
        body: dict = {"jsonrpc": "2.0", "method": method}
        if not notification:
            body["id"] = self._rid
        if params is not None:
            body["params"] = params
        url = f"{self._host}/api/2.0/mcp/genie/{space_id}"
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
        req.add_header("Authorization", f"Bearer {self._token_provider()}")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json, text/event-stream")
        req.add_header("MCP-Protocol-Version", self._protocol_version)
        with urllib.request.urlopen(req) as r:
            raw = r.read().decode()
        if notification or not raw.strip():
            return None
        # The managed server replies with plain JSON, but accept SSE framing too.
        if raw.lstrip().startswith("{"):
            return json.loads(raw)
        for line in raw.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        return None

    def _handshake(self, space_id: str) -> None:
        self._rpc(space_id, "initialize", {
            "protocolVersion": self._protocol_version,
            "capabilities": {},
            "clientInfo": {"name": "lead-opt-app", "version": "1.0"},
        })
        self._rpc(space_id, "notifications/initialized", notification=True)

    def _call_tool(self, space_id: str, name: str, arguments: dict) -> dict:
        resp = self._rpc(space_id, "tools/call", {"name": name, "arguments": arguments})
        result = (resp or {}).get("result", {})
        sc = result.get("structuredContent")
        if sc is not None:
            return sc
        # Fallback: parse the first JSON text block if structuredContent is absent.
        for block in result.get("content", []) or []:
            if block.get("type") == "text":
                try:
                    return json.loads(block["text"])
                except (ValueError, KeyError):
                    continue
        return {}

    # -- public: one interface for any room -------------------------------
    def ask(self, space_id: str, question: str, *, max_polls: int = 40,
            poll_seconds: float = 3.0) -> dict:
        """Ask one question of a Genie space via MCP; poll to completion.

        Returns {status, text, sql, rows, conversation_id} — the same shape the
        old REST path returned, so callers are unchanged apart from passing a
        space_id. `rows` is a list of plain lists (typed values flattened)."""
        try:
            self._handshake(space_id)
            qtool = f"query_space_{space_id}"
            ptool = f"poll_response_{space_id}"
            sc = self._call_tool(space_id, qtool, {"query": question})
            conv = sc.get("conversationId")
            msg = sc.get("messageId")
            status = sc.get("status")
            polls = 0
            while status not in _TERMINAL and conv and msg and polls < max_polls:
                time.sleep(poll_seconds)
                sc = self._call_tool(space_id, ptool,
                                     {"conversation_id": conv, "message_id": msg})
                status = sc.get("status")
                polls += 1
            return {"conversation_id": conv, **self._parse_answer(sc, status)}
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:500] if hasattr(e, "read") else str(e)
            return {"status": "ERROR", "text": f"MCP HTTP {e.code}: {detail}",
                    "sql": None, "rows": None, "conversation_id": None}

    @staticmethod
    def _parse_answer(sc: dict, status: str | None) -> dict:
        content = sc.get("content", {}) if isinstance(sc, dict) else {}
        texts = content.get("textAttachments") or []
        text = "\n".join(t for t in texts if t) or None
        sql, rows = None, None
        for qa in content.get("queryAttachments") or []:
            if qa.get("query"):
                sql = qa["query"]
            res = (qa.get("statement_response") or {}).get("result") or {}
            data = res.get("data_array")
            if data is not None:
                rows = [GenieMCP._flatten_row(r) for r in data]
        return {"status": status, "text": text, "sql": sql, "rows": rows}

    @staticmethod
    def _flatten_row(row):
        """MCP wraps rows as {'values':[{'string_value':..}, ...]}; flatten to a list.
        Plain lists (older shapes) are returned as-is."""
        if isinstance(row, dict) and "values" in row:
            out = []
            for cell in row["values"]:
                if isinstance(cell, dict):
                    out.append(next(iter(cell.values()), None) if cell else None)
                else:
                    out.append(cell)
            return out
        return row
