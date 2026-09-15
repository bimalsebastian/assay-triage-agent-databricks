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
import urllib.request

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

import lakebase  # deployed alongside this file (copy of serving/lakebase.py)
from genie_mcp import GenieMCP  # deployed alongside this file (copy of genie/genie_mcp.py)

HOST = os.environ["DATABRICKS_HOST"].rstrip("/")
if not HOST.startswith("http"):  # Apps set DATABRICKS_HOST without a scheme
    HOST = "https://" + HOST
CLIENT_ID = os.environ["DATABRICKS_CLIENT_ID"]
CLIENT_SECRET = os.environ["DATABRICKS_CLIENT_SECRET"]
GENIE_SPACE_ID = os.environ["GENIE_SPACE_ID"]
# Separate, scoped clinical room (stage 12). Optional so the app still boots if
# the clinical extension isn't deployed; the clinical tab is hidden when unset.
CLINICAL_GENIE_SPACE_ID = os.environ.get("CLINICAL_GENIE_SPACE_ID", "")
LAKEBASE_HOST = os.environ["LAKEBASE_HOST"]
PGDATABASE = os.environ.get("PGDATABASE", "lead_opt")
WAREHOUSE_ID = os.environ["WAREHOUSE_ID"]

# One Genie client (Databricks Managed MCP) addresses BOTH rooms by space id.
# The named rooms below are all it will route to — the preclinical room and the
# separate aggregate-only clinical room keep their distinct scopes/grants; this
# is just a single transport in front of them.
GENIE_ROOMS = {"preclinical": GENIE_SPACE_ID}
if CLINICAL_GENIE_SPACE_ID:
    GENIE_ROOMS["clinical"] = CLINICAL_GENIE_SPACE_ID

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


def warehouse_query(sql: str) -> list[dict]:
    """Run a read query against the SQL warehouse as the app SP (has SELECT on
    silver + CAN_USE on the warehouse). Used for compound history from Delta."""
    body = {"warehouse_id": WAREHOUSE_ID, "statement": sql,
            "wait_timeout": "30s", "on_wait_timeout": "CANCEL"}
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{HOST}/api/2.0/sql/statements", data=data, method="POST")
    req.add_header("Authorization", f"Bearer {_oauth_token()}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as r:
        resp = json.loads(r.read().decode())
    cols = [c["name"] for c in resp.get("manifest", {}).get("schema", {}).get("columns", [])]
    rows = resp.get("result", {}).get("data_array", []) or []
    return [dict(zip(cols, row)) for row in rows]


# Single unified Genie interface over Databricks Managed MCP. Authenticates as
# the app SP (same OAuth token used for Lakebase and the warehouse); routes to
# whichever room the caller names.
_genie_client = GenieMCP(HOST, _oauth_token)


def ask_genie(question: str, room: str = "preclinical") -> dict:
    space_id = GENIE_ROOMS.get(room)
    if not space_id:
        return {"status": "ERROR", "text": f"unknown room '{room}'",
                "sql": None, "rows": None, "room": room}
    result = _genie_client.ask(space_id, question)
    result["room"] = room
    return result


def _user(request: Request) -> str:
    return (request.headers.get("X-Forwarded-Email")
            or request.headers.get("X-Forwarded-Preferred-Username")
            or request.headers.get("X-Forwarded-User")
            or "unknown-user")


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
def clinical_summary(compound: str):
    """Aggregate clinical-correlation summary for a compound, read from the
    stage-12 SCOPED view (clinical_correlation_summary) — the same aggregate
    surface the clinical Genie room uses. The app SP can read only this view,
    not the clinical catalog tables (verified in stage 12), so this is not a
    backdoor into clinical data."""
    try:
        c = compound.replace("'", "")
        rows = warehouse_query(
            "SELECT compound_id, correlation_state, n_adverse_obs, signal_summary "
            "FROM lead_opt_demo.silver.clinical_correlation_summary "
            f"WHERE compound_id = '{c}'")
        return {"compound_id": compound, "summary": rows[0] if rows else None}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


@app.get("/api/history")
def history(compound: str, assay: str):
    """Real historical readings for a compound+assay from silver.assay_results."""
    try:
        c = compound.replace("'", "")
        a = assay.replace("'", "")
        rows = warehouse_query(
            "SELECT assay_name, result_value, result_unit, "
            "cast(acquired_ts AS STRING) AS acquired_ts, qc_flag "
            "FROM lead_opt_demo.silver.assay_results "
            f"WHERE compound_id = '{c}' AND assay_name = '{a}' "
            "ORDER BY acquired_ts")
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


@app.get("/api/rooms")
def rooms():
    """Which Genie rooms this app can address (drives the ask-box selector)."""
    return {"rooms": list(GENIE_ROOMS.keys())}


@app.post("/api/ask")
async def ask(request: Request):
    body = await request.json()
    q = (body.get("question") or "").strip()
    room = (body.get("room") or "preclinical").strip()
    if not q:
        return JSONResponse({"error": "empty question"}, status_code=400)
    if room not in GENIE_ROOMS:
        return JSONResponse({"error": f"unknown room '{room}'",
                             "allowed": list(GENIE_ROOMS)}, status_code=400)
    return ask_genie(q, room)


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
 main{max-width:1120px;margin:20px auto;padding:0 16px}
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
 #answer{white-space:pre-wrap;background:#f0f4f2;border-radius:8px;padding:12px;margin-top:10px;font-size:13px;min-height:20px}
 code{background:#eef1f4;padding:1px 5px;border-radius:4px;font-size:12px}
 .muted{color:#8a97a5;font-size:12px}
 .kpi{font-size:26px;font-weight:700;color:#0b3d2e}
 .bar{height:14px;background:#0b3d2e;border-radius:3px;display:inline-block}
 .htab td,.htab th{padding:4px 8px;font-size:12px}
 .cc{display:inline-block;padding:2px 9px;border-radius:20px;font-size:11px;font-weight:600;border:1px solid transparent}
 .cc.correlated{background:#fdeaea;color:#b3261e;border-color:#f3c0c0}
 .cc.checked{background:#eef1f4;color:#41505f}
 .cc.nomap{background:transparent;color:#8a97a5;border-color:#d5dbe1;border-style:dashed}
</style></head><body>
<header><h1>Lead-Opt Assay Triage — review queue</h1><span id="user"></span></header>
<main>
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
 <div class="card">
  <h2>Ask a Genie room <span class="muted">via Databricks Managed MCP</span></h2>
  <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
   <select id="room" title="Which governed Genie room to ask"></select>
   <input id="q" placeholder="e.g. Which compounds are currently flagged?" style="flex:1;min-width:220px">
   <button onclick="ask()">Ask</button></div>
  <div id="roomNote" class="muted" style="margin-top:6px"></div>
  <div id="answer" class="muted" style="margin-top:8px">Answers come from the governed silver tables via the selected Genie room (one MCP interface, room-scoped).</div>
  <div id="sql" class="muted" style="margin-top:8px"></div>
 </div>
</main>
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
const ROOM_LABELS={preclinical:'Preclinical (assay silver)',clinical:'Clinical correlation (aggregate-only, scoped)'};
const ROOM_HINT={preclinical:'Governed preclinical silver tables.',clinical:'Separate scoped room — aggregate correlation summary only, no patient-level data.'};
async function loadRooms(){
 const sel=document.getElementById('room');const d=await(await fetch('/api/rooms')).json();
 sel.innerHTML=(d.rooms||[]).map(r=>`<option value="${r}">${ROOM_LABELS[r]||r}</option>`).join('');
 sel.onchange=()=>{document.getElementById('roomNote').textContent=ROOM_HINT[sel.value]||'';};
 sel.onchange();
}
async function ask(){
 const q=document.getElementById('q').value;const room=document.getElementById('room').value;
 const a=document.getElementById('answer');const s=document.getElementById('sql');
 if(!q)return;a.textContent='Thinking… ('+(ROOM_LABELS[room]||room)+')';s.textContent='';
 const d=await(await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q,room:room})})).json();
 a.textContent=d.text||('(no text answer; status '+d.status+')');
 if(d.sql){s.innerHTML='<code>'+d.sql.replace(/</g,'&lt;')+'</code>';}
}
whoami();loadRooms();loadKpi();loadFba();loadRollup();
</script>
</body></html>"""
