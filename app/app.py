"""Lead-Opt Assay Triage — review dashboard (Databricks App).

The business-facing end of the chain: a reviewer opens this, sees the current
flagged-compound queue (from Lakebase, stage 03), sees WHY each is flagged
(reasoning carried inline), marks items resolved, and asks the Genie space
(stage 04) follow-up questions inline.

Auth: runs behind Databricks Apps workspace SSO. The signed-in user's identity
arrives in the X-Forwarded-Email header and is recorded as the resolver.

Data/AI access is a HYBRID identity model:
- Governed reads + Genie run ON BEHALF OF the signed-in USER. Databricks forwards
  the user's OAuth token (scopes `sql`, `genie`) as the X-Forwarded-Access-Token
  header on every request; the app uses it as the bearer for warehouse queries and
  the Genie One MCP. Unity Catalog then enforces THAT user's grants — including
  row filters and column masks — so clinical data is denied per the real person,
  not uniformly per a shared identity.
- Operational plumbing (the Lakebase review queue: reads, resolution writes) runs
  as the app's own SERVICE PRINCIPAL (client-credentials OAuth minted at runtime
  from the DATABRICKS_CLIENT_ID/SECRET the Apps runtime injects). The queue is
  operational serving, not the governed system of record (Delta is), and the
  background sync has no user in the loop — so an app identity is correct there.
  Lakebase SP tokens expire ~1h, so a fresh one is minted per connection.
"""
from __future__ import annotations

import json
import os
import urllib.request

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

import lakebase  # deployed alongside this file (copy of serving/lakebase.py)
from genie_mcp import GenieOneMCP  # deployed alongside this file (copy of genie/genie_mcp.py)

HOST = os.environ["DATABRICKS_HOST"].rstrip("/")
if not HOST.startswith("http"):  # Apps set DATABRICKS_HOST without a scheme
    HOST = "https://" + HOST
CLIENT_ID = os.environ["DATABRICKS_CLIENT_ID"]
CLIENT_SECRET = os.environ["DATABRICKS_CLIENT_SECRET"]
LAKEBASE_HOST = os.environ["LAKEBASE_HOST"]
PGDATABASE = os.environ.get("PGDATABASE", "lead_opt")
WAREHOUSE_ID = os.environ["WAREHOUSE_ID"]

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


def warehouse_query(sql: str, token: str) -> list[dict]:
    """Run a read query against the SQL warehouse ON BEHALF OF the signed-in user
    (their forwarded token). Unity Catalog enforces THAT user's grants + any row
    filters / column masks on silver, so results are scoped to what they may see."""
    body = {"warehouse_id": WAREHOUSE_ID, "statement": sql,
            "wait_timeout": "30s", "on_wait_timeout": "CANCEL"}
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{HOST}/api/2.0/sql/statements", data=data, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as r:
        resp = json.loads(r.read().decode())
    cols = [c["name"] for c in resp.get("manifest", {}).get("schema", {}).get("columns", [])]
    rows = resp.get("result", {}).get("data_array", []) or []
    return [dict(zip(cols, row)) for row in rows]


# Genie One managed MCP: ONE workspace-wide endpoint that routes each question to
# the right data itself (no space selection). Called ON BEHALF OF the signed-in
# user (their forwarded token), so Unity Catalog scopes the answer to what THAT
# user may access — patient-level clinical data is denied per their own grants.
# The client is created per-request (below) since the user token is per-request.


def _user(request: Request) -> str:
    return (request.headers.get("X-Forwarded-Email")
            or request.headers.get("X-Forwarded-Preferred-Username")
            or request.headers.get("X-Forwarded-User")
            or "unknown-user")


def _user_token(request: Request) -> str | None:
    """The signed-in user's forwarded OAuth token (Databricks Apps user
    authorization). Present when the app has `sql`/`genie` user_api_scopes and the
    user has consented. None locally / if scopes aren't configured."""
    return request.headers.get("X-Forwarded-Access-Token")


def _genie_for(request: Request) -> GenieOneMCP:
    """A Genie One MCP client bound to this request's user token (OBO)."""
    tok = _user_token(request)
    return GenieOneMCP(HOST, lambda: tok)


@app.get("/api/whoami")
def whoami(request: Request):
    return {"user": _user(request)}


def _json_safe(obj):
    if isinstance(obj, list):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    return obj.isoformat() if hasattr(obj, "isoformat") else obj


@app.get("/api/queue/rollup")
def queue_rollup():
    """Compound-level rollup (one row per compound, readings nested), blended-risk
    sorted (clinical correlation first), with a clinical-convergence headline."""
    try:
        return {"summary": lakebase.get_queue_summary(),
                "convergence": _json_safe(lakebase.get_clinical_convergence()),
                "compounds": _json_safe(lakebase.get_queue_rollup())}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


@app.get("/api/flags-by-assay")
def flags_by_assay(days: int = 30):
    try:
        return {"days": days, "by_assay": _json_safe(lakebase.get_flags_by_assay(days))}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


@app.get("/api/kpi")
def kpi():
    try:
        k = lakebase.get_kpi()
        for hkey, skey in (("median_hours", "median_seconds"), ("p90_hours", "p90_seconds")):
            s = k.get(skey)
            k[hkey] = round(s / 3600, 2) if s is not None else None
        return k
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


@app.get("/api/clinical-summary")
def clinical_summary(request: Request, compound: str):
    """Aggregate clinical-correlation summary for a compound, read ON BEHALF OF
    the signed-in user from the stage-12 SCOPED view (clinical_correlation_summary)
    — the same aggregate surface the clinical Genie room uses. Unity Catalog
    enforces the user's own grants: a user without access to this view gets nothing
    back, so clinical visibility is per-person, not a shared backdoor."""
    tok = _user_token(request)
    if not tok:
        return JSONResponse({"error": "user_authorization_required"}, status_code=401)
    try:
        c = compound.replace("'", "")
        rows = warehouse_query(
            "SELECT compound_id, correlation_state, n_adverse_obs, signal_summary "
            "FROM lead_opt_demo.silver.clinical_correlation_summary "
            f"WHERE compound_id = '{c}'", tok)
        return {"compound_id": compound, "summary": rows[0] if rows else None}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


@app.get("/api/history")
def history(request: Request, compound: str, assay: str):
    """Real historical readings for a compound+assay from silver.assay_results,
    read on behalf of the signed-in user (UC enforces their grants)."""
    tok = _user_token(request)
    if not tok:
        return JSONResponse({"error": "user_authorization_required"}, status_code=401)
    try:
        c = compound.replace("'", "")
        a = assay.replace("'", "")
        rows = warehouse_query(
            "SELECT assay_name, result_value, result_unit, "
            "cast(acquired_ts AS STRING) AS acquired_ts, qc_flag "
            "FROM lead_opt_demo.silver.assay_results "
            f"WHERE compound_id = '{c}' AND assay_name = '{a}' "
            "ORDER BY acquired_ts", tok)
        return {"compound_id": compound, "assay_name": assay, "readings": rows}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


@app.post("/api/resolve")
async def resolve(request: Request):
    body = await request.json()
    reason = body.get("resolution_reason")
    if reason not in lakebase.RESOLUTION_REASONS:
        return JSONResponse(
            {"error": "resolution_reason required",
             "allowed": list(lakebase.RESOLUTION_REASONS)}, status_code=400)
    try:
        ok = lakebase.resolve_item(body["reading_id"], _user(request), reason, body.get("note"))
        return {"ok": ok}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


@app.post("/api/ask")
async def ask(request: Request):
    """Start a Genie One question and return immediately with ids to poll.
    Genie One is async and can take ~30s+; the browser polls /api/ask/poll so the
    request never hangs behind the Apps proxy timeout."""
    body = await request.json()
    q = (body.get("question") or "").strip()
    if not q:
        return JSONResponse({"error": "empty question"}, status_code=400)
    if not _user_token(request):
        return JSONResponse({"error": "user_authorization_required"}, status_code=401)
    return _genie_for(request).start(q, conversation_id=body.get("conversation_id"))


@app.get("/api/ask/poll")
def ask_poll(request: Request, conversation_id: str, response_id: str):
    if not _user_token(request):
        return JSONResponse({"error": "user_authorization_required"}, status_code=401)
    return _genie_for(request).poll(conversation_id, response_id)


@app.get("/api/ask/query-result")
def ask_query_result(request: Request, conversation_id: str, response_id: str, item_id: str):
    """Rows behind one of Genie's query_items, fetched as the signed-in user so
    the app can render Genie's own data natively (table + chart)."""
    if not _user_token(request):
        return JSONResponse({"error": "user_authorization_required"}, status_code=401)
    return _genie_for(request).query_result(conversation_id, response_id, item_id)


@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX_HTML


INDEX_HTML = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>Lead-Opt Assay Triage</title>
<style>
 body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f6f7f9;color:#1b1f24}
 header{background:#0b3d2e;color:#fff;padding:14px 22px;display:flex;justify-content:space-between;align-items:center}
 header h1{font-size:17px;margin:0;font-weight:600}
 #user{font-size:13px;opacity:.85}
 main{max-width:1520px;margin:20px auto;padding:0 16px}
 .shell{display:flex;gap:18px;align-items:flex-start}
 .content{flex:1;min-width:0}
 .chat{width:400px;flex:none;position:sticky;top:20px}
 .chat .card{display:flex;flex-direction:column;max-height:calc(100vh - 40px);margin-bottom:0}
 @media(max-width:980px){.shell{flex-direction:column}.chat{width:auto;position:static}.chat .card{max-height:none}}
 .card{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:16px 18px;margin-bottom:18px}
 h2{font-size:14px;text-transform:uppercase;letter-spacing:.04em;color:#5a6b7b;margin:0 0 12px}
 .grid{display:grid;grid-template-columns:1fr 2fr;gap:18px}
 @media(max-width:720px){.grid{grid-template-columns:1fr}}
 table{width:100%;border-collapse:collapse;font-size:13px}
 th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #eef1f4;vertical-align:top}
 th{color:#5a6b7b;font-weight:600}
 .reason{color:#444;font-size:12px}
 .pill{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:600}
 .low{background:#fdeaea;color:#b3261e}.high{background:#fff3e0;color:#b26a00}
 .crow{cursor:pointer}.crow:hover{background:#f6faf8}
 .badge{display:inline-block;min-width:20px;text-align:center;background:#0b3d2e;color:#fff;border-radius:20px;padding:1px 8px;font-size:12px;font-weight:600}
 .detail{background:#f9fbfa;border-left:3px solid #0b3d2e}
 button{background:#0b3d2e;color:#fff;border:0;border-radius:6px;padding:6px 12px;font-size:12px;cursor:pointer}
 button:disabled{opacity:.5}
 select,input{font:inherit;padding:6px 8px;border:1px solid #ccd2d9;border-radius:6px}
 input{width:100%;box-sizing:border-box}
 #answer{white-space:pre-wrap;background:#f0f4f2;border-radius:8px;padding:12px;margin-top:10px;font-size:13px;min-height:20px;flex:1;overflow:auto}
 code{background:#eef1f4;padding:1px 5px;border-radius:4px;font-size:12px}
 .muted{color:#8a97a5;font-size:12px}
 .kpi{font-size:26px;font-weight:700;color:#0b3d2e}
 .bar{height:14px;background:#0b3d2e;border-radius:3px;display:inline-block}
 .htab td,.htab th{padding:4px 8px;font-size:12px}
 .cc{display:inline-block;padding:2px 9px;border-radius:20px;font-size:11px;font-weight:600;border:1px solid transparent}
 .cc.correlated{background:#fdeaea;color:#b3261e;border-color:#f3c0c0}
 .cc.checked{background:#eef1f4;color:#41505f}
 .cc.nomap{background:transparent;color:#8a97a5;border-color:#d5dbe1;border-style:dashed}
 .trace{margin:0 0 10px;border-left:2px solid #d7e3dc;padding-left:10px}
 .trace .step{font-size:12px;color:#41505f;padding:2px 0;display:flex;gap:6px;align-items:baseline}
 .trace .step .mk{flex:none;font-size:11px}
 .trace .step.run .mk{color:#b26a00}.trace .step.think .mk{color:#0b3d2e}
 .trace.live .step:last-child{color:#0b3d2e;font-weight:600}
 .trace.done{opacity:.7}
 .final{margin-top:4px}
 details.explain{margin-top:12px;border-top:1px solid #eef1f4;padding-top:8px}
 details.explain>summary{cursor:pointer;font-size:12px;color:#0b3d2e;font-weight:600;list-style:none}
 details.explain>summary::-webkit-details-marker{display:none}
 details.explain>summary::before{content:'▸ ';}
 details.explain[open]>summary::before{content:'▾ ';}
 .qi{margin:10px 0}
 .qi .qh{font-size:11px;color:#5a6b7b;font-weight:600;margin-bottom:4px}
 pre.sql{background:#14231e;color:#d6e9df;padding:9px 10px;border-radius:6px;overflow:auto;font-size:11px;line-height:1.45;font-family:'DM Mono',ui-monospace,SFMono-Regular,monospace;white-space:pre;margin:0 0 6px}
 .chart{margin:6px 0}
 .chart .row{display:flex;align-items:center;gap:6px;font-size:11px;margin:2px 0}
 .chart .row .lbl{flex:none;width:110px;text-align:right;color:#41505f;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .chart .row .track{flex:1;background:#eef1f4;border-radius:3px;overflow:hidden}
 .chart .row .fill{height:12px;background:#0b3d2e;border-radius:3px}
 .chart .row .val{flex:none;color:#5a6b7b;min-width:44px}
</style></head><body>
<header><h1>Lead-Opt Assay Triage — review queue</h1><span id="user"></span></header>
<main><div class="shell">
 <div class="content">
 <div class="grid">
  <div class="card">
   <h2>Triage KPIs <span class="muted" id="kpiNote"></span></h2>
   <div style="display:flex;gap:22px;flex-wrap:wrap;align-items:flex-end">
    <div><div class="kpi" id="kpiMedian">—</div><div class="muted">median flag&rarr;resolve</div></div>
    <div><div class="kpi" id="kpiP90">—</div><div class="muted">p90 flag&rarr;resolve</div></div>
    <div><div class="kpi" id="kpiFp">—</div><div class="muted">false-positive rate</div></div>
   </div>
   <div id="mix" style="margin-top:12px"></div>
  </div>
  <div class="card">
   <h2>Open flags by assay <span class="muted" id="fbaDays"></span></h2>
   <table id="fba"><tbody></tbody></table>
  </div>
 </div>
 <div class="card">
  <h2>Compounds with open flags <span id="count" class="muted"></span></h2>
  <div id="convergence" style="margin:2px 0 12px;font-size:13px"></div>
  <table id="rollup"><thead><tr>
   <th></th><th>Compound</th><th>Open flags</th><th>Worst breach</th><th>Clinical correlation</th>
  </tr></thead><tbody></tbody></table>
  <div class="muted" style="margin-top:8px">Click a compound to expand its flagged readings (widest breach first), resolve them, see its assay history, and the scoped clinical summary. Clinical states are rendered distinctly: <span class="cc correlated">correlated</span> <span class="cc checked">checked, no correlation</span> <span class="cc nomap">no clinical data</span>.</div>
 </div>
 </div>
 <aside class="chat">
  <div class="card">
   <h2>Ask Genie <span class="muted">via Genie One MCP (one surface, auto-routed)</span></h2>
   <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
    <input id="q" placeholder="e.g. Which compounds are flagged, and do any correlate with a clinical signal?" style="flex:1;min-width:200px">
    <button onclick="ask()">Ask</button></div>
   <div id="answer" class="muted" style="margin-top:10px">One natural-language surface over the whole workspace — Genie One routes the question to the right governed data itself; no room to pick. Answers run <b>as you</b> (on-behalf-of-user): Unity Catalog scopes every result to your own grants, so patient-level clinical data is denied per your access, not a shared identity.</div>
   <div id="deep" style="margin-top:8px"></div>
  </div>
 </aside>
</div></main>
<script>
const REASONS=[["false_positive","False positive"],["confirmed_concern","Confirmed concern"],["escalated_for_confirmatory_assay","Escalate for confirmatory assay"]];
function ccBadge(state){
 if(state==='correlated')return '<span class="cc correlated">⚠ correlated</span>';
 if(state==='checked_no_correlation')return '<span class="cc checked">checked · no correlation</span>';
 if(state==='no_mapping')return '<span class="cc nomap">no clinical data</span>';
 return '<span class="cc nomap">—</span>';
}
async function whoami(){const d=await(await fetch('/api/whoami')).json();document.getElementById('user').textContent=d.user;}
async function loadKpi(){
 const d=await(await fetch('/api/kpi')).json();
 document.getElementById('kpiMedian').textContent=(d.median_hours!=null)?(d.median_hours+' h'):'—';
 document.getElementById('kpiP90').textContent=(d.p90_hours!=null)?(d.p90_hours+' h'):'—';
 document.getElementById('kpiFp').textContent=(d.false_positive_rate!=null)?(Math.round(d.false_positive_rate*100)+'%'):'—';
 document.getElementById('kpiNote').textContent=(d.resolved_count?('from '+d.resolved_count+' real resolution'+(d.resolved_count==1?'':'s')):'no resolutions logged yet');
 const mix=d.outcome_mix||{};
 const seg=[['false_positive','False positive','#b3261e'],['confirmed_concern','Confirmed concern','#b26a00'],['escalated_for_confirmatory_assay','Escalated','#0b3d2e']];
 const total=seg.reduce((s,x)=>s+(mix[x[0]]||0),0);
 const box=document.getElementById('mix');
 if(!total){box.innerHTML='<span class="muted">Resolution-outcome mix appears once flags are resolved.</span>';return;}
 let bar='<div style="display:flex;height:16px;border-radius:4px;overflow:hidden;max-width:440px">';
 seg.forEach(s=>{const v=mix[s[0]]||0;if(v)bar+=`<div title="${s[1]}: ${v}" style="width:${100*v/total}%;background:${s[2]}"></div>`;});
 bar+='</div>';
 let leg='<div class="muted" style="margin-top:6px">';
 seg.forEach(s=>{const v=mix[s[0]]||0;leg+=`<span style="margin-right:14px"><span style="display:inline-block;width:9px;height:9px;background:${s[2]};border-radius:2px;margin-right:4px"></span>${s[1]} ${v}</span>`;});
 leg+='</div>';
 box.innerHTML='<div class="muted" style="margin-bottom:4px">Resolution-outcome mix (real reviewer decisions)</div>'+bar+leg;
}
async function loadFba(){
 const d=await(await fetch('/api/flags-by-assay')).json();
 document.getElementById('fbaDays').textContent='(last '+d.days+' days)';
 const tb=document.querySelector('#fba tbody');tb.innerHTML='';
 const max=Math.max(1,...d.by_assay.map(x=>x.open_flags));
 d.by_assay.forEach(x=>{const tr=document.createElement('tr');
  tr.innerHTML=`<td>${x.assay_name}</td><td style="width:60%"><span class="bar" style="width:${100*x.open_flags/max}%"></span> ${x.open_flags}</td>`;tb.appendChild(tr);});
 if(!d.by_assay.length)tb.innerHTML='<tr><td class="muted">No open flags.</td></tr>';
}
async function loadRollup(){
 const d=await(await fetch('/api/queue/rollup')).json();
 document.getElementById('count').textContent='('+(d.summary.open||0)+' open flags across '+d.compounds.length+' compounds)';
 const cv=d.convergence||{};const bs=cv.by_state||{};const cbox=document.getElementById('convergence');
 if(cv.compounds_open){
  cbox.innerHTML='<b style="color:#b3261e">'+(cv.correlated||0)+' of '+cv.compounds_open+'</b> open compounds show a clinical correlation'
   +' ('+Math.round((cv.convergence_rate||0)*100)+'% convergence). '
   +'<span class="cc correlated">correlated '+(bs.correlated||0)+'</span> '
   +'<span class="cc checked">checked '+(bs.checked_no_correlation||0)+'</span> '
   +'<span class="cc nomap">no clinical data '+(bs.no_mapping||0)+'</span>'
   +'<div class="muted" style="margin-top:4px">Rows are blended-risk sorted: clinically-correlated compounds first, then flag count, then breach.</div>';
 } else { cbox.innerHTML=''; }
 const tb=document.querySelector('#rollup tbody');tb.innerHTML='';
 d.compounds.forEach(c=>{
  const tr=document.createElement('tr');tr.className='crow';tr.onclick=()=>toggle(c,tr);
  tr.innerHTML=`<td>▶</td><td><b>${c.compound_id}</b></td><td><span class="badge">${c.open_flags}</span></td><td>${(+c.worst_breach).toFixed(3)}</td><td>${ccBadge(c.clinical_correlation_state)}</td>`;
  tb.appendChild(tr);
 });
 if(!d.compounds.length)tb.innerHTML='<tr><td colspan=5 class="muted">Queue is empty.</td></tr>';
}
function toggle(c,tr){
 if(tr.nextSibling && tr.nextSibling.classList && tr.nextSibling.classList.contains('detail')){tr.nextSibling.remove();tr.cells[0].textContent='▶';return;}
 tr.cells[0].textContent='▼';
 const det=document.createElement('tr');det.className='detail';
 const td=document.createElement('td');td.colSpan=5;det.appendChild(td);
 let html='<table><thead><tr><th>Assay</th><th>Reading</th><th>Threshold</th><th>Breach</th><th>Why</th><th>Resolve</th></tr></thead><tbody>';
 c.readings.forEach((r,i)=>{
  const dir=(r.concern_direction==='high')?'high':'low';
  const opts=REASONS.map(x=>`<option value="${x[0]}">${x[1]}</option>`).join('');
  html+=`<tr><td>${r.assay_name}</td><td>${r.result_value} ${r.result_unit||''}</td>
   <td><span class="pill ${dir}">${r.threshold} ${dir}</span></td>
   <td>${Math.abs(r.margin).toFixed(3)}</td>
   <td class="reason">${r.reason||''}</td>
   <td><select id="sel_${r.reading_id}"><option value="">reason…</option>${opts}</select>
   <button onclick="resolve('${r.reading_id}',this)">Resolve</button></td></tr>`;
 });
 html+='</tbody></table>';
 html+='<div style="margin-top:10px">Clinical correlation: '+ccBadge(c.clinical_correlation_state)+' <span id="clin_'+c.compound_id+'" class="muted"></span></div>';
 html+='<div id="hist_'+c.compound_id+'" class="muted" style="margin-top:8px">loading history…</div>';
 td.innerHTML=html;tr.after(det);
 loadHistory(c);loadClinical(c);
}
async function loadClinical(c){
 const box=document.getElementById('clin_'+c.compound_id);
 const d=await(await fetch('/api/clinical-summary?compound='+encodeURIComponent(c.compound_id))).json();
 const s=d.summary;
 box.textContent = s ? ('— '+s.signal_summary+' (adverse obs: '+s.n_adverse_obs+') · via scoped clinical_correlation_summary view')
                     : '— no scoped clinical summary row';
}
async function loadHistory(c){
 const assays=[...new Set(c.readings.map(r=>r.assay_name))];
 const box=document.getElementById('hist_'+c.compound_id);box.innerHTML='';
 for(const a of assays){
  const d=await(await fetch('/api/history?compound='+encodeURIComponent(c.compound_id)+'&assay='+encodeURIComponent(a))).json();
  let h='<div style="margin-top:6px"><b>'+c.compound_id+' · '+a+'</b> — historical readings</div>';
  h+='<table class="htab"><thead><tr><th>acquired</th><th>value</th><th>unit</th><th>qc</th></tr></thead><tbody>';
  (d.readings||[]).forEach(x=>{h+=`<tr><td>${x.acquired_ts}</td><td>${x.result_value}</td><td>${x.result_unit||''}</td><td>${x.qc_flag||''}</td></tr>`;});
  h+='</tbody></table>';box.innerHTML+=h;
 }
}
async function resolve(id,btn){
 const sel=document.getElementById('sel_'+id);const reason=sel.value;
 if(!reason){sel.style.borderColor='#b3261e';return;}
 btn.disabled=true;btn.textContent='…';
 const r=await fetch('/api/resolve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reading_id:id,resolution_reason:reason,note:'resolved from dashboard'})});
 if(r.ok){await loadRollup();await loadKpi();await loadFba();}else{btn.disabled=false;btn.textContent='Resolve';}
}
function escHtml(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function mdInline(s){
 s=escHtml(s);
 s=s.replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
 s=s.replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>');
 s=s.replace(/`([^`]+)`/g,'<code>$1</code>');
 return s;
}
function mdToHtml(md){
 if(!md)return '';
 const lines=md.split('\n');let html='';let i=0;
 while(i<lines.length){
  const line=lines[i];
  if(line.indexOf('|')>=0 && i+1<lines.length && lines[i+1].indexOf('-')>=0 && /^[\s:|-]+$/.test(lines[i+1])){
   let header=line.split('|').map(c=>c.trim());
   if(header[0]==='')header.shift(); if(header.length&&header[header.length-1]==='')header.pop();
   i+=2;let rows=[];
   while(i<lines.length && lines[i].indexOf('|')>=0){
    let cells=lines[i].split('|').map(c=>c.trim());
    if(cells[0]==='')cells.shift(); if(cells.length&&cells[cells.length-1]==='')cells.pop();
    rows.push(cells);i++;
   }
   html+='<div style="overflow-x:auto"><table class="htab"><thead><tr>'+header.map(h=>'<th>'+mdInline(h)+'</th>').join('')+'</tr></thead><tbody>';
   rows.forEach(r=>{html+='<tr>'+r.map(c=>'<td>'+mdInline(c)+'</td>').join('')+'</tr>';});
   html+='</tbody></table></div>';continue;
  }
  if(/^#{1,6}\s/.test(line)){const lvl=line.match(/^#+/)[0].length;html+='<div style="font-weight:600;margin:8px 0 4px;font-size:'+(15-lvl)+'px">'+mdInline(line.replace(/^#+\s*/,''))+'</div>';i++;continue;}
  if(line.trim()===''){i++;continue;}
  html+='<div style="margin:2px 0">'+mdInline(line)+'</div>';i++;
 }
 return html;
}
const TERMINAL=['completed','incomplete','failed','cancelled','error'];
function sleep(ms){return new Promise(r=>setTimeout(r,ms));}
function stepClass(s){const l=(s||'').toLowerCase();return (l.startsWith('running sql')||l.indexOf('query')>=0)?'run':'think';}
function renderTrace(el,steps,live){
 el.className='trace'+(live?' live':' done');
 el.innerHTML=(steps&&steps.length?steps:['Sending question to Genie…']).map(s=>{
  const c=stepClass(s);return `<div class="step ${c}"><span class="mk">${c==='run'?'▷':'•'}</span><span>${escHtml(s)}</span></div>`;
 }).join('');
}
function chartHtml(cols,rows){
 if(!cols||!rows||!rows.length)return '';
 const isNum=v=>v!==null&&v!==''&&!isNaN(+v);
 let numIdx=-1;for(let c=0;c<cols.length;c++){if(rows.every(r=>isNum(r[c]))){numIdx=c;break;}}
 if(numIdx<0)return '';
 let lblIdx=-1;for(let c=0;c<cols.length;c++){if(c!==numIdx&&rows.some(r=>!isNum(r[c]))){lblIdx=c;break;}}
 if(lblIdx<0)lblIdx=(numIdx===0?Math.min(1,cols.length-1):0);
 const data=rows.slice(0,15).map(r=>({l:String(r[lblIdx]==null?'':r[lblIdx]),v:+r[numIdx]}));
 const max=Math.max(...data.map(d=>Math.abs(d.v)),1);
 let h='<div class="chart"><div class="qh">'+escHtml(cols[lblIdx])+' &times; '+escHtml(cols[numIdx])+'</div>';
 data.forEach(d=>{h+=`<div class="row"><span class="lbl" title="${escHtml(d.l)}">${escHtml(d.l)}</span><span class="track"><span class="fill" style="width:${Math.max(2,100*Math.abs(d.v)/max)}%"></span></span><span class="val">${d.v}</span></div>`;});
 return h+'</div>';
}
function tableHtml(cols,rows){
 if(!cols.length)return '';
 let h='<div style="overflow-x:auto"><table class="htab"><thead><tr>'+cols.map(c=>'<th>'+escHtml(c)+'</th>').join('')+'</tr></thead><tbody>';
 rows.slice(0,25).forEach(r=>{h+='<tr>'+r.map(c=>'<td>'+escHtml(String(c==null?'':c))+'</td>').join('')+'</tr>';});
 return h+'</tbody></table></div>';
}
async function renderExplain(container,d,qs){
 const items=d.query_items||[];
 if(!items.length)return;
 const det=document.createElement('details');det.className='explain';
 det.innerHTML='<summary>How Genie got this — '+items.length+' quer'+(items.length===1?'y':'ies')+' + data</summary>';
 container.appendChild(det);
 for(let i=0;i<items.length;i++){
  const it=items[i];const box=document.createElement('div');box.className='qi';
  box.innerHTML='<div class="qh">Query '+(i+1)+'</div><pre class="sql">'+escHtml(it.sql||'(sql unavailable)')+'</pre><div class="qr muted" style="font-size:11px">loading rows…</div>';
  det.appendChild(box);
  try{
   const qr=await(await fetch('/api/ask/query-result?'+qs+'&item_id='+encodeURIComponent(it.item_id))).json();
   const cols=qr.columns||[],rows=qr.rows||[];
   let html=chartHtml(cols,rows)+tableHtml(cols,rows);
   if(qr.truncated)html+='<div class="muted" style="font-size:11px">First rows'+(qr.total_row_count?(' of '+qr.total_row_count):'')+' — open in Genie for the full result.</div>';
   box.querySelector('.qr').innerHTML=html||'<span class="muted">no rows</span>';box.querySelector('.qr').className='qr';
  }catch(e){ box.querySelector('.qr').innerHTML='<span class="muted">could not load rows</span>'; }
 }
}
async function ask(){
 const q=document.getElementById('q').value.trim();
 const a=document.getElementById('answer');const dp=document.getElementById('deep');
 if(!q)return;
 a.className='';a.innerHTML='<div class="trace live" id="trace"></div>';dp.innerHTML='';
 const trace=document.getElementById('trace');renderTrace(trace,[],true);
 let s;
 try{ s=await(await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q})})).json(); }
 catch(e){ a.className='muted';a.textContent='(request failed)'; return; }
 if(s.status==='error'||!s.conversation_id||!s.response_id){a.className='muted';a.textContent='(could not start: '+(s.error||s.status)+')';return;}
 const qs='conversation_id='+encodeURIComponent(s.conversation_id)+'&response_id='+encodeURIComponent(s.response_id);
 let d=s,steps=[];
 for(let i=0;i<80 && !TERMINAL.includes((d.status||'').toLowerCase());i++){
  await sleep(2500);
  try{ d=await(await fetch('/api/ask/poll?'+qs)).json(); }catch(e){ /* transient */ }
  if(d.progress_steps&&d.progress_steps.length){steps=d.progress_steps;renderTrace(trace,steps,true);}
 }
 renderTrace(trace,steps,false);
 const fin=document.createElement('div');fin.className='final';
 fin.innerHTML=d.text?mdToHtml(d.text):'<span class="muted">(no answer; status '+(d.status||'timeout')+')</span>';
 a.appendChild(fin);
 await renderExplain(a,d,qs);
 if(d.deep_link){dp.innerHTML='<a href="'+d.deep_link+'" target="_blank" rel="noopener">Open the full answer &amp; visualizations in Genie One ↗</a>';}
}
whoami();loadKpi();loadFba();loadRollup();
</script>
</body></html>"""
