"""Lead-Opt Assay Triage — review dashboard (Databricks App).

The business-facing end of the chain: a reviewer opens this, sees the current
flagged-compound queue (from Lakebase, stage 03), sees WHY each is flagged
(reasoning carried inline), marks items resolved, and asks the Genie space
(stage 04) follow-up questions inline.

Auth: runs behind Databricks Apps workspace SSO. The signed-in user's identity
arrives in the X-Forwarded-Email header and is recorded as the resolver.

Data/AI access: authenticates to both Lakebase and the Genie Conversations API
as the app's own service principal (client-credentials OAuth minted at runtime
from the DATABRICKS_CLIENT_ID/SECRET the Apps runtime injects). Lakebase tokens
expire ~1h, so a fresh token is minted per connection via a credential provider.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

import lakebase  # deployed alongside this file (copy of serving/lakebase.py)

HOST = os.environ["DATABRICKS_HOST"].rstrip("/")
if not HOST.startswith("http"):  # Apps set DATABRICKS_HOST without a scheme
    HOST = "https://" + HOST
CLIENT_ID = os.environ["DATABRICKS_CLIENT_ID"]
CLIENT_SECRET = os.environ["DATABRICKS_CLIENT_SECRET"]
GENIE_SPACE_ID = os.environ["GENIE_SPACE_ID"]
LAKEBASE_HOST = os.environ["LAKEBASE_HOST"]
PGDATABASE = os.environ.get("PGDATABASE", "lead_opt")

app = FastAPI(title="Lead-Opt Assay Triage")


def _oauth_token() -> str:
    """Mint an app-SP OAuth token (client-credentials)."""
    body = b"grant_type=client_credentials&scope=all-apis"
    req = urllib.request.Request(f"{HOST}/oidc/v1/token", data=body, method="POST")
    import base64
    basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    req.add_header("Authorization", f"Basic {basic}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode())["access_token"]


# Lakebase connects as the app SP, fresh token per connection.
lakebase.set_credential_provider(lambda: {
    "host": LAKEBASE_HOST, "port": 5432, "dbname": PGDATABASE,
    "user": CLIENT_ID, "password": _oauth_token(), "sslmode": "require",
})


def _genie(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{HOST}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {_oauth_token()}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode())


def ask_genie(question: str) -> dict:
    sp = GENIE_SPACE_ID
    start = _genie("POST", f"/api/2.0/genie/spaces/{sp}/start-conversation",
                   {"content": question})
    conv = start.get("conversation_id") or start["conversation"]["id"]
    msg = start.get("message_id") or start["message"]["id"]
    m = {}
    for _ in range(40):
        m = _genie("GET", f"/api/2.0/genie/spaces/{sp}/conversations/{conv}/messages/{msg}")
        if m.get("status") in ("COMPLETED", "FAILED", "CANCELLED"):
            break
        time.sleep(3)
    text, sql, rows = None, None, None
    for att in m.get("attachments", []) or []:
        if att.get("text"):
            text = att["text"].get("content")
        if att.get("query"):
            sql = att["query"].get("query")
            aid = att.get("attachment_id")
            try:
                qr = _genie("GET", f"/api/2.0/genie/spaces/{sp}/conversations/{conv}"
                                   f"/messages/{msg}/attachments/{aid}/query-result")
                rows = qr.get("statement_response", {}).get("result", {}).get("data_array")
            except Exception:  # noqa: BLE001
                rows = None
    return {"status": m.get("status"), "text": text, "sql": sql, "rows": rows}


def _user(request: Request) -> str:
    return (request.headers.get("X-Forwarded-Email")
            or request.headers.get("X-Forwarded-Preferred-Username")
            or request.headers.get("X-Forwarded-User")
            or "unknown-user")


@app.get("/api/whoami")
def whoami(request: Request):
    return {"user": _user(request)}


@app.get("/api/queue")
def queue():
    try:
        items = lakebase.get_review_queue("open")
        summary = lakebase.get_queue_summary()
        for it in items:  # JSON-safe (timestamps -> str)
            for k, v in list(it.items()):
                if hasattr(v, "isoformat"):
                    it[k] = v.isoformat()
        return {"summary": summary, "items": items}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


@app.post("/api/resolve")
async def resolve(request: Request):
    body = await request.json()
    ok = lakebase.resolve_item(body["reading_id"], _user(request), body.get("note"))
    return {"ok": ok}


@app.post("/api/ask")
async def ask(request: Request):
    body = await request.json()
    q = (body.get("question") or "").strip()
    if not q:
        return JSONResponse({"error": "empty question"}, status_code=400)
    return ask_genie(q)


@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX_HTML


INDEX_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Lead-Opt Assay Triage</title>
<style>
 body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f6f7f9;color:#1b1f24}
 header{background:#0b3d2e;color:#fff;padding:14px 22px;display:flex;justify-content:space-between;align-items:center}
 header h1{font-size:17px;margin:0;font-weight:600}
 #user{font-size:13px;opacity:.85}
 main{max-width:1100px;margin:20px auto;padding:0 16px}
 .card{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:16px 18px;margin-bottom:18px}
 h2{font-size:14px;text-transform:uppercase;letter-spacing:.04em;color:#5a6b7b;margin:0 0 12px}
 table{width:100%;border-collapse:collapse;font-size:13px}
 th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #eef1f4;vertical-align:top}
 th{color:#5a6b7b;font-weight:600}
 .reason{color:#444;font-size:12px;max-width:420px}
 .pill{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:600}
 .low{background:#fdeaea;color:#b3261e}.high{background:#fff3e0;color:#b26a00}
 button{background:#0b3d2e;color:#fff;border:0;border-radius:6px;padding:6px 12px;font-size:12px;cursor:pointer}
 button.sec{background:#e7eb0f0;background:#eef1f4;color:#1b1f24}
 input,textarea{font:inherit;padding:8px 10px;border:1px solid #ccd2d9;border-radius:6px;width:100%;box-sizing:border-box}
 #answer{white-space:pre-wrap;background:#f0f4f2;border-radius:8px;padding:12px;margin-top:10px;font-size:13px;min-height:20px}
 code{background:#eef1f4;padding:1px 5px;border-radius:4px;font-size:12px}
 .muted{color:#8a97a5;font-size:12px}
</style></head><body>
<header><h1>Lead-Opt Assay Triage — review queue</h1><span id="user"></span></header>
<main>
 <div class="card">
  <h2>Open review queue <span id="count" class="muted"></span></h2>
  <table id="queue"><thead><tr>
   <th>Compound</th><th>Assay</th><th>Reading</th><th>Threshold</th><th>Why flagged</th><th></th>
  </tr></thead><tbody></tbody></table>
 </div>
 <div class="card">
  <h2>Ask the Genie space</h2>
  <div style="display:flex;gap:8px"><input id="q" placeholder="e.g. Which compounds are currently flagged?"><button onclick="ask()">Ask</button></div>
  <div id="answer" class="muted">Answers come from the governed silver tables via the Genie space.</div>
  <div id="sql" class="muted" style="margin-top:8px"></div>
 </div>
</main>
<script>
async function whoami(){const r=await fetch('/api/whoami');const d=await r.json();document.getElementById('user').textContent=d.user;}
async function load(){
 const r=await fetch('/api/queue');const d=await r.json();
 const tb=document.querySelector('#queue tbody');tb.innerHTML='';
 document.getElementById('count').textContent='('+(d.summary.open||0)+' open)';
 d.items.forEach(it=>{
  const tr=document.createElement('tr');
  const dir=(it.concern_direction==='high')?'high':'low';
  tr.innerHTML=`<td><b>${it.compound_id}</b></td><td>${it.assay_name}</td>
   <td>${it.result_value} ${it.result_unit||''}</td>
   <td><span class="pill ${dir}">${it.threshold} ${it.threshold_unit||''} ${dir}</span></td>
   <td class="reason">${it.reason||''}</td>
   <td><button class="sec" onclick="resolve('${it.reading_id}',this)">Resolve</button></td>`;
  tb.appendChild(tr);
 });
 if(!d.items.length){tb.innerHTML='<tr><td colspan=6 class="muted">Queue is empty.</td></tr>';}
}
async function resolve(id,btn){
 btn.disabled=true;btn.textContent='...';
 await fetch('/api/resolve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reading_id:id,note:'resolved from dashboard'})});
 load();
}
async function ask(){
 const q=document.getElementById('q').value;const a=document.getElementById('answer');const s=document.getElementById('sql');
 if(!q)return;a.textContent='Thinking…';s.textContent='';
 const r=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q})});
 const d=await r.json();
 a.textContent=d.text||('(no text answer; status '+d.status+')');
 if(d.sql){s.innerHTML='<code>'+d.sql.replace(/</g,'&lt;')+'</code>';}
}
whoami();load();
</script>
</body></html>"""
