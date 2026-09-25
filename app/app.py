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
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Lead-Opt Assay Triage — Discovery OS</title>
<script src="https://cdn.tailwindcss.com?plugins=forms,container-queries"></script>
<link href="https://fonts.googleapis.com" rel="preconnect"/>
<link crossorigin="" href="https://fonts.gstatic.com" rel="preconnect"/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet"/>
<script>
 tailwind.config = { theme: { extend: {
   fontFamily: { sans: ['Inter','system-ui','sans-serif'], mono: ['JetBrains Mono','monospace'] },
   colors: { brand: { 50:'#F0FDFA',100:'#CCFBF1',500:'#14B8A6',600:'#0D9488',700:'#0F766E',900:'#134E4A' } }
 } } };
</script>
<style>
 ::-webkit-scrollbar{width:6px;height:6px}
 ::-webkit-scrollbar-track{background:#F1F5F9}
 ::-webkit-scrollbar-thumb{background:#CBD5E1;border-radius:9999px}
 ::-webkit-scrollbar-thumb:hover{background:#94A3B8}
 .chev{display:inline-block;transition:transform .15s}
 .chev.open{transform:rotate(90deg)}
 /* markdown answer internals */
 .md > div{margin:2px 0}
 .md b, .md strong{font-weight:600;color:#0f172a}
 .md a{color:#0f766e;text-decoration:underline}
 .md code{background:#f1f5f9;padding:1px 4px;border-radius:4px;font-family:'JetBrains Mono',monospace;font-size:11px}
 .md table.htab{width:100%;border-collapse:collapse;margin:6px 0;font-size:11px}
 .md table.htab th{background:#f1f5f9;color:#64748b;text-align:left;padding:4px 8px;font-weight:600}
 .md table.htab td{padding:4px 8px;border-top:1px solid #f1f5f9;color:#475569;vertical-align:top}
 details > summary{list-style:none}
 details > summary::-webkit-details-marker{display:none}
</style>
</head>
<body class="bg-[#F8FAFC] text-slate-900 font-sans antialiased min-h-screen flex flex-col">

<header class="bg-white border-b border-slate-200 sticky top-0 z-40 px-6 py-2.5 shadow-sm">
<div class="max-w-[1720px] mx-auto flex items-center justify-between">
 <div class="flex items-center space-x-6">
  <div class="flex items-center space-x-2.5">
   <div class="w-8 h-8 rounded-lg bg-teal-600 flex items-center justify-center text-white font-bold shadow-sm">
    <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2.2" viewBox="0 0 24 24"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>
   </div>
   <div>
    <div class="flex items-center space-x-1.5">
     <span class="text-sm font-bold tracking-tight text-slate-900 leading-none">Lead-Opt Triage</span>
     <span class="text-[10px] font-semibold uppercase bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded border border-slate-200">Discovery OS</span>
    </div>
    <div class="text-[10px] text-slate-400 mt-0.5">Assay triage &amp; clinical convergence</div>
   </div>
  </div>
  <div class="hidden lg:flex items-center space-x-2.5 px-3 py-1 rounded-full bg-slate-50 border border-slate-200">
   <span class="flex h-2 w-2 relative"><span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span><span class="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span></span>
   <span class="text-[11px] font-medium text-slate-600">Governed by <span class="font-semibold text-slate-800">Unity Catalog</span></span>
   <span class="text-slate-300">•</span>
   <span class="text-[11px] text-slate-500">on-behalf-of-user</span>
  </div>
 </div>
 <div class="flex items-center space-x-4">
  <div class="relative hidden md:block">
   <span class="absolute inset-y-0 left-0 pl-2.5 flex items-center pointer-events-none text-slate-400"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"></path></svg></span>
   <input class="w-60 pl-8 pr-3 py-1 bg-slate-50 border border-slate-200 rounded-md text-xs placeholder:text-slate-400 focus:bg-white focus:outline-none focus:ring-1 focus:ring-teal-500 focus:border-teal-500 transition" placeholder="Jump to compound, assay..." type="text"/>
  </div>
  <div class="h-4 w-px bg-slate-200"></div>
  <div class="flex items-center space-x-2 pl-1">
   <div id="userInit" class="w-7 h-7 rounded-full bg-teal-700 text-white flex items-center justify-center font-medium text-xs">–</div>
   <div class="text-left hidden sm:block">
    <p id="user" class="text-xs font-semibold text-slate-800 leading-none">…</p>
    <p class="text-[10px] text-slate-400 leading-tight mt-0.5">Triage Lead</p>
   </div>
  </div>
  <div class="h-4 w-px bg-slate-200"></div>
  <button onclick="signOut()" title="Sign out &amp; re-authorize — clears this app's cached session so newly-granted permissions (e.g. genie) take effect" class="p-1.5 rounded-md hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"></path></svg></button>
 </div>
</div>
</header>

<main class="flex-1 max-w-[1720px] w-full mx-auto px-6 py-6">
<div class="grid grid-cols-12 gap-6 items-start">

 <!-- LEFT WORKSPACE -->
 <section class="col-span-12 lg:col-span-8 flex flex-col space-y-6">

  <!-- Top metrics row -->
  <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
   <!-- Triage KPIs -->
   <div class="bg-white rounded-xl border border-slate-200/80 p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)] flex flex-col justify-between">
    <div>
     <div class="flex items-center justify-between pb-3 border-b border-slate-100">
      <div class="flex items-center space-x-2">
       <h3 class="text-xs font-bold uppercase tracking-wider text-slate-500">Triage KPIs</h3>
       <span id="kpiCount" class="text-[11px] font-medium text-teal-700 bg-teal-50 px-2 py-0.5 rounded-full border border-teal-200/50">…</span>
      </div>
     </div>
     <div class="grid grid-cols-3 gap-3 mt-4">
      <div>
       <div class="text-[11px] font-medium text-slate-500 leading-tight">Median flag→resolve</div>
       <div class="flex items-baseline space-x-1.5 mt-1"><span id="kpiMedian" class="text-2xl font-bold tracking-tight text-slate-900 font-mono">—</span><span class="text-xs text-slate-500 font-medium">h</span></div>
       <span id="kpiMedianNote" class="inline-flex items-center text-[10px] text-emerald-600 font-medium mt-0.5"></span>
      </div>
      <div>
       <div class="text-[11px] font-medium text-slate-500 leading-tight">P90 flag→resolve</div>
       <div class="flex items-baseline space-x-1.5 mt-1"><span id="kpiP90" class="text-2xl font-bold tracking-tight text-slate-900 font-mono">—</span><span class="text-xs text-slate-500 font-medium">h</span></div>
       <span class="inline-flex items-center text-[10px] text-slate-400 font-medium mt-0.5">Target &lt; 24.0h</span>
      </div>
      <div>
       <div class="text-[11px] font-medium text-slate-500 leading-tight">False-positive rate</div>
       <div class="flex items-baseline space-x-1 mt-1"><span id="kpiFp" class="text-2xl font-bold tracking-tight text-slate-900 font-mono">—</span><span class="text-sm font-semibold text-slate-600">%</span></div>
       <span id="kpiFpNote" class="inline-flex items-center text-[10px] text-amber-600 font-medium mt-0.5"></span>
      </div>
     </div>
    </div>
    <div class="mt-5 pt-4 border-t border-slate-100">
     <div class="flex justify-between items-center mb-1.5"><span class="text-[11px] font-semibold text-slate-600">Resolution-Outcome Mix</span><span class="text-[10px] text-slate-400">Real reviewer decisions</span></div>
     <div id="mixBar" class="w-full h-3 rounded-full bg-slate-100 flex overflow-hidden p-0.5 gap-0.5"></div>
     <div id="mixLeg" class="flex items-center justify-between text-[11px] mt-2 text-slate-600"></div>
    </div>
   </div>
   <!-- Open Flags by Assay -->
   <div class="bg-white rounded-xl border border-slate-200/80 p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)] flex flex-col justify-between">
    <div>
     <div class="flex items-center justify-between pb-3 border-b border-slate-100">
      <div class="flex items-center space-x-2"><h3 class="text-xs font-bold uppercase tracking-wider text-slate-500">Open Flags by Assay</h3><span id="fbaDays" class="text-[11px] font-medium text-slate-500 bg-slate-100 px-2 py-0.5 rounded-full">Last 30 Days</span></div>
     </div>
     <div id="fba" class="space-y-3.5 mt-4"></div>
    </div>
    <div class="text-[11px] text-slate-400 mt-2 flex items-center justify-between pt-3 border-t border-slate-100">
     <span>Widest-breach assays float to the top of the queue.</span>
     <span id="fbaTotal" class="font-mono font-semibold text-slate-600">Total: —</span>
    </div>
   </div>
  </div>

  <!-- Compounds table -->
  <div class="bg-white rounded-xl border border-slate-200/80 shadow-[0_1px_3px_rgba(0,0,0,0.04)] overflow-hidden">
   <div class="p-5 border-b border-slate-200 bg-white">
    <div class="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
     <div>
      <div class="flex items-center space-x-2">
       <h2 class="text-sm font-bold uppercase tracking-wider text-slate-800">Compounds with Open Flags</h2>
       <span id="count" class="text-xs font-semibold px-2 py-0.5 rounded-md bg-rose-50 text-rose-700 border border-rose-200">…</span>
       <span id="live" class="text-[10px] text-slate-400 inline-flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span><span id="liveTxt">live</span></span>
      </div>
      <div id="convergence" class="flex flex-wrap items-center gap-2 mt-2"></div>
     </div>
     <div class="flex items-center space-x-2">
      <input id="filter" oninput="applyFilter()" class="text-xs px-2.5 py-1.5 border border-slate-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-teal-500 w-36 sm:w-44" placeholder="Filter compound..." type="text"/>
      <span class="inline-flex items-center space-x-1 px-3 py-1.5 rounded-lg border border-slate-200 text-xs font-medium text-slate-700 bg-slate-50"><svg class="w-3.5 h-3.5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"></path></svg><span>Blended-risk</span></span>
     </div>
    </div>
    <p class="text-xs text-slate-500 mt-2">Rows are blended-risk sorted: clinically-correlated compounds first, then flag count, then breach severity.</p>
   </div>
   <div class="overflow-x-auto">
    <table id="rollup" class="w-full text-left text-xs">
     <thead class="bg-slate-50/75 border-b border-slate-200 text-slate-500 font-medium">
      <tr><th class="py-3 pl-4 pr-1 w-8"></th><th class="py-3 px-3">Compound</th><th class="py-3 px-3">Open Flags</th><th class="py-3 px-3">Worst Breach</th><th class="py-3 px-3">Clinical Correlation</th><th class="py-3 pr-4 text-right">Actions</th></tr>
     </thead>
     <tbody class="divide-y divide-slate-100"></tbody>
    </table>
   </div>
   <div class="px-5 py-3 bg-slate-50 border-t border-slate-200/80 flex flex-col sm:flex-row items-start sm:items-center justify-between text-[11px] text-slate-500 gap-2">
    <div class="flex items-center space-x-2"><svg class="w-4 h-4 text-slate-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"></path></svg><span>Click a compound to inspect its flagged readings, resolve them, and see assay history + the scoped clinical summary.</span></div>
    <div class="flex items-center space-x-1.5 shrink-0"><span class="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-rose-50 text-rose-700 border border-rose-200">correlated</span><span class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-100 text-slate-600">checked</span><span class="px-1.5 py-0.5 rounded text-[10px] font-medium border border-dashed border-slate-300 text-slate-400">no clinical</span></div>
   </div>
  </div>
 </section>

 <!-- RIGHT COPILOT -->
 <aside class="col-span-12 lg:col-span-4 lg:sticky lg:top-[76px] flex flex-col">
  <div class="bg-white rounded-xl border border-slate-200/80 shadow-[0_1px_3px_rgba(0,0,0,0.04)] flex flex-col h-[78vh] overflow-hidden">
   <div class="p-4 border-b border-slate-200 bg-gradient-to-r from-white via-teal-50/20 to-white flex items-center justify-between">
    <div class="flex items-center space-x-2.5">
     <div class="w-7 h-7 rounded-lg bg-teal-600 text-white flex items-center justify-center shadow-sm"><svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M13 10V3L4 14h7v7l9-11h-7z" stroke-linecap="round" stroke-linejoin="round"></path></svg></div>
     <div><div class="flex items-center space-x-1.5"><h3 class="text-sm font-bold text-slate-900 tracking-tight">Ask Genie</h3><span class="text-[10px] font-semibold uppercase bg-teal-100 text-teal-800 px-1.5 py-0.5 rounded border border-teal-200/50">One MCP</span></div><p class="text-[10px] text-slate-400">One surface, auto-routed. Runs as you (UC-governed).</p></div>
    </div>
    <div class="flex items-center space-x-1 bg-emerald-50 text-emerald-700 border border-emerald-200/60 px-2 py-0.5 rounded-full text-[10px] font-medium"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span><span>Online</span></div>
   </div>
   <div class="px-4 py-2 bg-slate-50 border-b border-slate-200 flex items-center space-x-1.5 overflow-x-auto text-[11px]">
    <span class="text-slate-400 shrink-0 font-medium">Quick:</span>
    <button onclick="askQuick('Which compounds are flagged, and do any correlate with a clinical signal?')" class="px-2 py-0.5 bg-white border border-slate-200 hover:border-teal-400 rounded-full text-slate-600 hover:text-teal-700 whitespace-nowrap transition">Flagged summary</button>
    <button onclick="askQuick('Which compounds breach the hERG_IC50 threshold and by how much?')" class="px-2 py-0.5 bg-white border border-slate-200 hover:border-teal-400 rounded-full text-slate-600 hover:text-teal-700 whitespace-nowrap transition">hERG outliers</button>
    <button onclick="askQuick('List every open flagged compound with its worst breach margin and clinical correlation state.')" class="px-2 py-0.5 bg-white border border-slate-200 hover:border-teal-400 rounded-full text-slate-600 hover:text-teal-700 whitespace-nowrap transition">Export triage list</button>
   </div>
   <div id="answer" class="flex-1 p-4 overflow-y-auto space-y-4"></div>
   <div class="p-3 border-t border-slate-200 bg-white">
    <div class="relative flex items-center">
     <input id="q" onkeydown="if(event.key==='Enter')ask()" class="w-full text-xs pl-3.5 pr-12 py-2.5 bg-slate-50 border border-slate-200 rounded-xl focus:outline-none focus:ring-1 focus:ring-teal-500 focus:bg-white text-slate-800 placeholder:text-slate-400 transition" placeholder="Ask Genie about assay results, triage history..." type="text"/>
     <div class="absolute right-1.5 flex items-center"><button onclick="ask()" class="bg-teal-700 hover:bg-teal-800 text-white p-1.5 rounded-lg transition shadow-sm"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M12 19V5m-7 7l7-7 7 7" stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5"></path></svg></button></div>
    </div>
    <div class="flex items-center justify-between mt-2 px-1 text-[10px] text-slate-400">
     <span>Genie One MCP · auto-routed</span>
     <span>Scoped by Unity Catalog to your access</span>
    </div>
   </div>
  </div>
 </aside>

</div>
</main>

<footer class="mt-auto border-t border-slate-200 bg-white py-3 px-6 text-xs text-slate-400">
<div class="max-w-[1720px] mx-auto flex flex-col sm:flex-row justify-between items-center gap-2">
 <div class="flex items-center space-x-4"><span>Lead-Opt Assay Triage · Databricks App</span><span>•</span><span>catalog lead_opt_demo</span></div>
 <div class="flex items-center space-x-3 text-[11px]"><span class="inline-flex items-center text-slate-500"><span class="w-2 h-2 rounded-full bg-emerald-500 mr-1.5"></span>Genie One MCP · governed OBO</span></div>
</div>
</footer>

<script>
const REASONS=[["false_positive","False positive"],["confirmed_concern","Confirmed concern"],["escalated_for_confirmatory_assay","Escalate for confirmatory assay"]];
const TERMINAL=['completed','incomplete','failed','cancelled','error'];
function sleep(ms){return new Promise(r=>setTimeout(r,ms));}
function escHtml(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
let USER_INIT='U';

// Databricks Apps keep their OWN encrypted session cookie (24h TTL), independent
// of the workspace session — so logging out of the workspace does NOT refresh a
// token cached before new user_api_scopes (e.g. genie) were granted. The
// documented fix is to hit the app front door's sign-out path, which clears that
// cookie and forces a fresh OAuth + consent (picking up the new scopes) next load.
function signOut(){
 try{localStorage.clear();sessionStorage.clear();}catch(e){}
 window.location.href='/.auth/sign_out';
}
function isScopeError(msg){return /scope|403|authoriz/i.test(String(msg||''));}
function reauthCta(){
 return '<div class="mt-2 rounded-lg border border-amber-200 bg-amber-50 p-2.5 text-[11px] text-amber-800">'
  +'<div class="font-semibold mb-1">Re-authorization needed</div>'
  +'This window is using a cached app session issued before the <code>genie</code> permission was granted. Logging out of the workspace doesn\'t clear it — re-authorize this app to refresh your token.'
  +'<button onclick="signOut()" class="block mt-2 px-2.5 py-1 rounded bg-amber-600 text-white font-medium hover:bg-amber-700 transition">Sign out &amp; re-authorize</button></div>';
}

function ccBadge(state){
 const base='inline-flex items-center px-2.5 py-1 rounded-full text-[11px] font-medium ';
 if(state==='correlated')return '<span class="'+base+'bg-rose-50 text-rose-700 border border-rose-200">&#9888; correlated</span>';
 if(state==='checked_no_correlation')return '<span class="'+base+'bg-slate-100 text-slate-700 border border-slate-200">checked &middot; no correlation</span>';
 if(state==='no_mapping')return '<span class="'+base+'bg-white text-slate-500 border border-dashed border-slate-300">no clinical data</span>';
 return '<span class="'+base+'bg-white text-slate-400 border border-dashed border-slate-300">&mdash;</span>';
}

async function whoami(){
 try{const d=await(await fetch('/api/whoami')).json();const u=d.user||'user';
  document.getElementById('user').textContent=u;
  const init=((u.split('@')[0]||u).split(/[.\s_-]+/).map(x=>x[0]||'').join('')||u[0]||'U').slice(0,2).toUpperCase();
  USER_INIT=init;document.getElementById('userInit').textContent=init;
 }catch(e){}
}

async function loadKpi(){
 const d=await(await fetch('/api/kpi')).json();
 const set=(id,v)=>{const el=document.getElementById(id);if(el)el.textContent=v;};
 set('kpiMedian',d.median_hours!=null?d.median_hours:'—');
 set('kpiP90',d.p90_hours!=null?d.p90_hours:'—');
 set('kpiFp',d.false_positive_rate!=null?Math.round(d.false_positive_rate*100):'—');
 set('kpiCount',d.resolved_count?(d.resolved_count+' real resolution'+(d.resolved_count==1?'':'s')):'no resolutions yet');
 set('kpiMedianNote',d.resolved_count?('from '+d.resolved_count+' resolved'):'awaiting resolutions');
 const mix=d.outcome_mix||{};const fp=mix.false_positive||0;const tot=Object.values(mix).reduce((a,b)=>a+(b||0),0);
 set('kpiFpNote',tot?(fp+' FP / '+tot+' resolved'):'—');
 const seg=[['false_positive','False positive','bg-rose-500'],['confirmed_concern','Confirmed concern','bg-amber-500'],['escalated_for_confirmatory_assay','Escalated','bg-slate-800']];
 const bar=document.getElementById('mixBar');const leg=document.getElementById('mixLeg');
 if(!tot){bar.innerHTML='';leg.innerHTML='<span class="text-slate-400 text-[11px]">Outcome mix appears once flags are resolved.</span>';return;}
 bar.innerHTML=seg.map((s,i)=>{const v=mix[s[0]]||0;return v?('<div class="h-full '+s[2]+(i===0?' rounded-l-full':'')+'" style="width:'+(100*v/tot)+'%" title="'+s[1]+': '+v+'"></div>'):'';}).join('');
 leg.innerHTML=seg.map(s=>{const v=mix[s[0]]||0;return '<div class="flex items-center space-x-1.5"><span class="w-2 h-2 rounded-full '+s[2]+'"></span><span>'+s[1]+' <strong class="text-slate-800">'+v+'</strong></span></div>';}).join('');
}

async function loadFba(){
 const d=await(await fetch('/api/flags-by-assay')).json();
 const box=document.getElementById('fba');const max=Math.max(1,...d.by_assay.map(x=>x.open_flags));let total=0;
 box.innerHTML=d.by_assay.map(x=>{total+=x.open_flags;const w=Math.max(6,100*x.open_flags/max);
  return '<div><div class="flex justify-between items-center text-xs mb-1"><span class="font-mono font-medium text-slate-700">'+escHtml(x.assay_name)+'</span><span class="font-semibold text-slate-900 bg-slate-100 px-1.5 py-0.5 rounded font-mono text-[11px]">'+x.open_flags+' flag'+(x.open_flags==1?'':'s')+'</span></div><div class="w-full bg-slate-100 rounded-full h-2.5 overflow-hidden"><div class="bg-teal-700 h-2.5 rounded-full" style="width:'+w+'%"></div></div></div>';
 }).join('')||'<div class="text-slate-400 text-xs">No open flags.</div>';
 document.getElementById('fbaTotal').textContent='Total: '+total;
 document.getElementById('fbaDays').textContent='Last '+d.days+' Days';
}

let MAX_BREACH=1;
async function loadRollup(){
 const d=await(await fetch('/api/queue/rollup')).json();
 const cv=d.convergence||{};const bs=cv.by_state||{};
 document.getElementById('count').textContent=(d.summary.open||0)+' open flags across '+d.compounds.length+' compounds';
 const conv=document.getElementById('convergence');
 if(cv.compounds_open){
  const rate=Math.round((cv.convergence_rate||0)*100);
  conv.innerHTML='<div class="w-full flex items-start gap-2 rounded-lg bg-rose-50/70 border border-rose-200/70 px-3 py-2 text-xs text-rose-900"><span class="text-rose-500 mt-0.5">&#9888;</span><span><b>'+(cv.correlated||0)+' of '+cv.compounds_open+'</b> open compounds carry a preclinical flag <b>and</b> a clinical adverse-event signal — <b>'+rate+'% convergence</b>. These float to the top of the queue for confirmatory review first.</span></div>'
   +'<span class="text-xs font-medium text-slate-600 bg-slate-100 px-2.5 py-0.5 rounded-full">checked: '+(bs.checked_no_correlation||0)+'</span>'
   +'<span class="text-xs font-medium text-slate-500 border border-dashed border-slate-300 px-2.5 py-0.5 rounded-full">no clinical data: '+(bs.no_mapping||0)+'</span>';
 } else conv.innerHTML='';
 const tb=document.querySelector('#rollup tbody');tb.innerHTML='';
 if(!d.compounds.length){tb.innerHTML='<tr><td colspan="6" class="py-6 text-center text-slate-400 text-xs">Queue is empty.</td></tr>';return;}
 MAX_BREACH=Math.max(1,...d.compounds.map(c=>Math.abs(+c.worst_breach)));
 d.compounds.forEach(c=>{
  const st=c.clinical_correlation_state;const corr=st==='correlated';
  const chip=corr?'text-teal-700 bg-teal-50 border-teal-200':'text-slate-700 bg-slate-100 border-slate-200';
  const bc=corr?['text-rose-600','bg-rose-100','bg-rose-500']:(st==='checked_no_correlation'?['text-amber-700','bg-amber-100','bg-amber-500']:['text-slate-700','bg-slate-100','bg-slate-500']);
  const breach=Math.abs(+c.worst_breach);const bw=Math.max(15,100*breach/MAX_BREACH);
  const tr=document.createElement('tr');tr.className='hover:bg-teal-50/30 transition group cursor-pointer';
  tr.setAttribute('data-cid',c.compound_id);tr.onclick=()=>toggle(c,tr);
  tr.innerHTML='<td class="py-3.5 pl-4 pr-1"><span class="chev text-slate-400">&#9656;</span></td>'
   +'<td class="py-3.5 px-3 font-mono font-semibold"><span class="px-2 py-0.5 rounded border '+chip+' transition">'+escHtml(c.compound_id)+'</span></td>'
   +'<td class="py-3.5 px-3"><span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold bg-slate-900 text-white">'+c.open_flags+'</span></td>'
   +'<td class="py-3.5 px-3 font-mono"><div class="flex items-center space-x-2"><span class="font-semibold '+bc[0]+'">'+breach.toFixed(3)+'</span><div class="w-12 '+bc[1]+' h-1.5 rounded-full overflow-hidden"><div class="'+bc[2]+' h-full" style="width:'+bw+'%"></div></div></div></td>'
   +'<td class="py-3.5 px-3">'+ccBadge(st)+'</td>'
   +'<td class="py-3.5 pr-4 text-right"><button class="px-2.5 py-1 text-[11px] font-medium text-teal-700 bg-teal-50 border border-teal-200 rounded hover:bg-teal-100 transition">Review</button></td>';
  tb.appendChild(tr);
 });
 applyFilter();
}
function applyFilter(){
 const q=(document.getElementById('filter').value||'').toLowerCase();
 document.querySelectorAll('#rollup tbody tr[data-cid]').forEach(tr=>{
  const hit=tr.getAttribute('data-cid').toLowerCase().indexOf(q)>=0;tr.style.display=hit?'':'none';
  const nx=tr.nextElementSibling;if(nx&&nx.classList.contains('detail'))nx.style.display=hit?'':'none';
 });
}

function toggle(c,tr){
 const nx=tr.nextElementSibling;const ch=tr.querySelector('.chev');
 if(nx&&nx.classList.contains('detail')){nx.remove();if(ch)ch.classList.remove('open');return;}
 if(ch)ch.classList.add('open');
 const det=document.createElement('tr');det.className='detail bg-slate-50/60';
 const td=document.createElement('td');td.colSpan=6;td.className='px-4 py-4';det.appendChild(td);
 let html='<div class="rounded-lg border border-slate-200 overflow-hidden bg-white"><table class="w-full text-left text-xs"><thead class="bg-slate-50 border-b border-slate-200 text-slate-500"><tr><th class="py-2 px-3 font-medium">Assay</th><th class="py-2 px-3 font-medium">Reading</th><th class="py-2 px-3 font-medium">Threshold</th><th class="py-2 px-3 font-medium">Breach</th><th class="py-2 px-3 font-medium">Why</th><th class="py-2 px-3 font-medium">Resolve</th></tr></thead><tbody class="divide-y divide-slate-100">';
 c.readings.forEach(r=>{
  const dir=(r.concern_direction==='high')?'high':'low';
  const pill=dir==='high'?'bg-amber-50 text-amber-700 border-amber-200':'bg-rose-50 text-rose-700 border-rose-200';
  const opts=REASONS.map(x=>'<option value="'+x[0]+'">'+x[1]+'</option>').join('');
  html+='<tr><td class="py-2 px-3 font-mono">'+escHtml(r.assay_name)+'</td><td class="py-2 px-3 font-mono">'+r.result_value+' '+escHtml(r.result_unit||'')+'</td><td class="py-2 px-3"><span class="inline-flex px-2 py-0.5 rounded-full text-[10px] font-medium border '+pill+'">'+r.threshold+' '+dir+'</span></td><td class="py-2 px-3 font-mono">'+Math.abs(r.margin).toFixed(3)+'</td><td class="py-2 px-3 text-slate-500 max-w-[280px]">'+escHtml(r.reason||'')+'</td><td class="py-2 px-3 whitespace-nowrap"><select id="sel_'+r.reading_id+'" class="text-[11px] border border-slate-200 rounded px-1.5 py-1 mr-1"><option value="">reason…</option>'+opts+'</select><button onclick="resolve(\''+r.reading_id+'\',this)" class="px-2 py-1 text-[11px] font-medium text-teal-700 bg-teal-50 border border-teal-200 rounded hover:bg-teal-100">Resolve</button></td></tr>';
 });
 html+='</tbody></table></div>';
 html+='<div class="mt-3 text-xs text-slate-600 flex items-center gap-2 flex-wrap">Clinical correlation: '+ccBadge(c.clinical_correlation_state)+' <span id="clin_'+c.compound_id+'" class="text-slate-400"></span></div>';
 html+='<div id="hist_'+c.compound_id+'" class="mt-2 text-xs text-slate-400">loading history…</div>';
 td.innerHTML=html;tr.after(det);
 loadHistory(c);loadClinical(c);
}
async function loadClinical(c){
 const box=document.getElementById('clin_'+c.compound_id);if(!box)return;
 try{const d=await(await fetch('/api/clinical-summary?compound='+encodeURIComponent(c.compound_id))).json();const s=d.summary;
  box.textContent=s?('— '+s.signal_summary+' (adverse obs: '+s.n_adverse_obs+') · via scoped clinical_correlation_summary'):'— no scoped clinical summary row';
 }catch(e){box.textContent='— clinical summary unavailable';}
}
async function loadHistory(c){
 const assays=[...new Set(c.readings.map(r=>r.assay_name))];
 const box=document.getElementById('hist_'+c.compound_id);if(!box)return;box.innerHTML='';
 for(const a of assays){
  try{const d=await(await fetch('/api/history?compound='+encodeURIComponent(c.compound_id)+'&assay='+encodeURIComponent(a))).json();
   let h='<div class="text-[11px] font-semibold text-slate-600 mt-2 mb-1 font-mono">'+escHtml(c.compound_id)+' · '+escHtml(a)+' — historical readings</div>';
   h+='<div class="rounded-lg border border-slate-200 overflow-x-auto bg-white"><table class="w-full text-left text-[11px] font-mono"><thead class="bg-slate-50 text-slate-500 border-b border-slate-200"><tr><th class="py-1.5 px-2">acquired</th><th class="py-1.5 px-2">value</th><th class="py-1.5 px-2">unit</th><th class="py-1.5 px-2">qc</th></tr></thead><tbody class="divide-y divide-slate-100">';
   (d.readings||[]).forEach(x=>{h+='<tr><td class="py-1 px-2 text-slate-600">'+escHtml(x.acquired_ts)+'</td><td class="py-1 px-2 text-slate-800">'+x.result_value+'</td><td class="py-1 px-2 text-slate-500">'+escHtml(x.result_unit||'')+'</td><td class="py-1 px-2 text-slate-500">'+escHtml(x.qc_flag||'')+'</td></tr>';});
   h+='</tbody></table></div>';box.innerHTML+=h;
  }catch(e){}
 }
}
async function resolve(id,btn){
 const sel=document.getElementById('sel_'+id);const reason=sel.value;
 if(!reason){sel.classList.add('ring-1','ring-rose-400');return;}
 btn.disabled=true;btn.textContent='…';
 const r=await fetch('/api/resolve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reading_id:id,resolution_reason:reason,note:'resolved from dashboard'})});
 if(r.ok){await loadRollup();await loadKpi();await loadFba();}else{btn.disabled=false;btn.textContent='Resolve';}
}

/* ---- markdown (compact) ---- */
function mdInline(s){s=escHtml(s);s=s.replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');s=s.replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>');s=s.replace(/`([^`]+)`/g,'<code>$1</code>');return s;}
function mdToHtml(md){
 if(!md)return '';const lines=md.split('\n');let html='';let i=0;
 while(i<lines.length){const line=lines[i];
  if(line.indexOf('|')>=0 && i+1<lines.length && /^[\s:|-]+$/.test(lines[i+1]) && lines[i+1].indexOf('-')>=0){
   let header=line.split('|').map(c=>c.trim());if(header[0]==='')header.shift();if(header.length&&header[header.length-1]==='')header.pop();
   i+=2;let rows=[];
   while(i<lines.length && lines[i].indexOf('|')>=0){let cells=lines[i].split('|').map(c=>c.trim());if(cells[0]==='')cells.shift();if(cells.length&&cells[cells.length-1]==='')cells.pop();rows.push(cells);i++;}
   html+='<table class="htab"><thead><tr>'+header.map(h=>'<th>'+mdInline(h)+'</th>').join('')+'</tr></thead><tbody>';
   rows.forEach(r=>{html+='<tr>'+r.map(c=>'<td>'+mdInline(c)+'</td>').join('')+'</tr>';});html+='</tbody></table>';continue;
  }
  if(/^#{1,6}\s/.test(line)){const lvl=line.match(/^#+/)[0].length;html+='<div style="font-weight:600;margin:8px 0 4px;font-size:'+(15-lvl)+'px">'+mdInline(line.replace(/^#+\s*/,''))+'</div>';i++;continue;}
  if(line.trim()===''){i++;continue;}
  html+='<div>'+mdInline(line)+'</div>';i++;
 }
 return html;
}

/* ---- Genie chat ---- */
function stepClass(s){const l=(s||'').toLowerCase();return (l.startsWith('running sql')||l.indexOf('query')>=0)?'run':'think';}
function renderTrace(el,steps,live){
 const list=(steps&&steps.length?steps:['Routing your question through Genie One…']);
 el.className='opacity-'+(live?'100':'70');
 el.innerHTML='<div class="border-l-2 border-teal-200 pl-2.5 space-y-1">'+list.map(s=>{const run=stepClass(s)==='run';return '<div class="flex items-start gap-1.5 text-[11px] '+(run?'text-amber-700':'text-slate-500')+'"><span>'+(run?'&#9655;':'&#8226;')+'</span><span>'+escHtml(s)+'</span></div>';}).join('')+(live?'<div class="text-[10px] text-teal-600 pl-3 animate-pulse">working…</div>':'')+'</div>';
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
 let h='<div class="mt-2"><div class="text-[10px] font-mono text-slate-500 mb-1">'+escHtml(cols[lblIdx])+' &times; '+escHtml(cols[numIdx])+'</div>';
 data.forEach(d=>{h+='<div class="flex items-center gap-2 text-[11px] my-0.5"><span class="w-24 text-right text-slate-500 truncate" title="'+escHtml(d.l)+'">'+escHtml(d.l)+'</span><div class="flex-1 bg-slate-100 rounded-full overflow-hidden h-3"><div class="bg-teal-600 h-3" style="width:'+Math.max(2,100*Math.abs(d.v)/max)+'%"></div></div><span class="w-10 text-slate-500 font-mono">'+d.v+'</span></div>';});
 return h+'</div>';
}
function tableHtml(cols,rows){
 if(!cols.length)return '';
 return '<div class="bg-white rounded-lg border border-slate-200 overflow-x-auto shadow-xs mt-1"><table class="w-full text-left text-[11px]"><thead class="bg-slate-100/70 border-b border-slate-200 font-mono text-slate-500 text-[10px]"><tr>'+cols.map(c=>'<th class="py-1.5 px-2 font-semibold">'+escHtml(c)+'</th>').join('')+'</tr></thead><tbody class="divide-y divide-slate-100 font-mono text-[11px]">'+rows.slice(0,25).map(r=>'<tr class="hover:bg-slate-50">'+r.map(x=>'<td class="py-1.5 px-2 text-slate-600">'+escHtml(String(x==null?'':x))+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
}
async function renderExplain(container,d,qs){
 const items=d.query_items||[];if(!items.length)return;
 const det=document.createElement('details');det.className='mt-1 border-t border-slate-200 pt-2';
 det.innerHTML='<summary class="cursor-pointer text-[11px] font-semibold text-teal-700">How Genie got this — '+items.length+' quer'+(items.length===1?'y':'ies')+'</summary>';
 container.appendChild(det);
 for(let i=0;i<items.length;i++){const it=items[i];const box=document.createElement('div');box.className='mt-2';
  box.innerHTML='<div class="text-[10px] font-mono text-slate-500 mb-1">Query '+(i+1)+'</div><pre class="bg-slate-900 text-teal-100 rounded-lg p-2.5 text-[10px] leading-relaxed overflow-x-auto font-mono whitespace-pre">'+escHtml(it.sql||'(sql unavailable)')+'</pre><div class="qr text-[11px] text-slate-400 mt-1">loading rows…</div>';
  det.appendChild(box);
  try{const qr=await(await fetch('/api/ask/query-result?'+qs+'&item_id='+encodeURIComponent(it.item_id))).json();
   const cols=qr.columns||[],rows=qr.rows||[];let html=chartHtml(cols,rows)+tableHtml(cols,rows);
   if(qr.truncated)html+='<div class="text-[10px] text-slate-400 mt-1">First rows'+(qr.total_row_count?(' of '+qr.total_row_count):'')+' — open in Genie for the full result.</div>';
   const el=box.querySelector('.qr');el.className='';el.innerHTML=html||'<span class="text-slate-400 text-[11px]">no rows</span>';
  }catch(e){const el=box.querySelector('.qr');if(el)el.textContent='could not load rows';}
 }
}
function scrollChat(){const a=document.getElementById('answer');a.scrollTop=a.scrollHeight;}
function genieHint(){
 return '<div class="flex items-start space-x-2.5"><div class="w-6 h-6 rounded-full bg-teal-600 text-white flex items-center justify-center shrink-0 mt-0.5 shadow-xs"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M13 10V3L4 14h7v7l9-11h-7z" stroke-linecap="round" stroke-linejoin="round"></path></svg></div><div class="bg-slate-50 border border-slate-200 rounded-2xl rounded-tl-sm p-3.5 text-[11px] text-slate-500 flex-1">Ask a question about the flagged compounds, assay thresholds, or clinical correlation. Genie One auto-routes it to the right governed data and answers <b class="text-slate-700">as you</b> — you\'ll see its thinking, the SQL it ran, and a chart from the result.</div></div>';
}
async function ask(){
 const inp=document.getElementById('q');const q=inp.value.trim();if(!q)return;
 const a=document.getElementById('answer');
 const ub=document.createElement('div');ub.className='flex items-start justify-end space-x-2';
 ub.innerHTML='<div class="bg-teal-700 text-white rounded-2xl rounded-tr-sm px-3.5 py-2 text-xs max-w-[85%] shadow-sm">'+escHtml(q)+'</div><div class="w-6 h-6 rounded-full bg-slate-200 text-slate-700 flex items-center justify-center font-bold text-[10px] shrink-0 mt-0.5">'+escHtml(USER_INIT)+'</div>';
 a.appendChild(ub);
 const wrap=document.createElement('div');wrap.className='flex items-start space-x-2.5';
 wrap.innerHTML='<div class="w-6 h-6 rounded-full bg-teal-600 text-white flex items-center justify-center shrink-0 mt-0.5 shadow-xs"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M13 10V3L4 14h7v7l9-11h-7z" stroke-linecap="round" stroke-linejoin="round"></path></svg></div><div class="bg-slate-50 border border-slate-200 rounded-2xl rounded-tl-sm p-3.5 text-xs text-slate-800 space-y-2.5 flex-1 shadow-sm min-w-0"><div class="flex items-center justify-between pb-2 border-b border-slate-200"><div class="flex items-center space-x-1.5"><span class="font-bold text-slate-900 text-xs">Genie Analysis</span><span class="text-[10px] text-teal-600 font-medium">via Genie One MCP</span></div><a class="deep text-[10px] font-semibold text-teal-700 hover:underline" href="#" target="_blank" rel="noopener" style="display:none">Open in Genie &rarr;</a></div><div class="tr"></div><div class="final md"></div><div class="explain"></div></div>';
 a.appendChild(wrap);
 const card=wrap.lastChild;const traceEl=card.querySelector('.tr');const finalEl=card.querySelector('.final');const explainEl=card.querySelector('.explain');const deepEl=card.querySelector('.deep');
 inp.value='';scrollChat();renderTrace(traceEl,[],true);
 let s;
 try{ s=await(await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q})})).json(); }
 catch(e){ finalEl.innerHTML='<span class="text-slate-400">(request failed)</span>'; return; }
 if(s.status==='error'||!s.conversation_id||!s.response_id){const msg=escHtml(s.error||s.status||'unknown');traceEl.innerHTML='';finalEl.innerHTML='<div class="text-slate-500">Could not start: '+msg+'</div>'+(isScopeError(s.error||s.status)?reauthCta():'');scrollChat();return;}
 const qs='conversation_id='+encodeURIComponent(s.conversation_id)+'&response_id='+encodeURIComponent(s.response_id);
 let d=s,steps=[];
 for(let i=0;i<80 && !TERMINAL.includes((d.status||'').toLowerCase());i++){
  await sleep(2500);
  try{ d=await(await fetch('/api/ask/poll?'+qs)).json(); }catch(e){}
  if(d.progress_steps&&d.progress_steps.length){steps=d.progress_steps;renderTrace(traceEl,steps,true);scrollChat();}
 }
 renderTrace(traceEl,steps,false);
 const st=(d.status||'').toLowerCase();
 if(d.text){finalEl.innerHTML=mdToHtml(d.text);}
 else if(st==='error'||st==='failed'){const msg=escHtml(d.error||d.text||'error');finalEl.innerHTML='<div class="text-slate-500">Genie error: '+msg+'</div>'+(isScopeError(d.error||d.text)?reauthCta():'');}
 else{finalEl.innerHTML='<span class="text-slate-400">(no answer; status '+escHtml(d.status||'timeout')+')</span>';}
 await renderExplain(explainEl,d,qs);
 if(d.deep_link){deepEl.href=d.deep_link;deepEl.style.display='';}
 scrollChat();
}
function askQuick(t){document.getElementById('q').value=t;ask();}

document.getElementById('answer').innerHTML=genieHint();
// Live operational view: auto-refresh KPI + flags + queue on an interval so new
// flags surface without a manual reload. The queue rebuild is SKIPPED while a
// reviewer has a row expanded, so auto-refresh never collapses their drill-in.
let LAST_REFRESH=Date.now();
async function refreshAll(){
 try{ await loadKpi(); await loadFba(); if(!document.querySelector('#rollup tbody tr.detail')){ await loadRollup(); } LAST_REFRESH=Date.now(); }catch(e){}
}
function tickLive(){const el=document.getElementById('liveTxt');if(!el)return;const s=Math.round((Date.now()-LAST_REFRESH)/1000);el.textContent='updated '+(s<60?(s+'s'):(Math.round(s/60)+'m'))+' ago';}
whoami();refreshAll();
setInterval(refreshAll,45000);
setInterval(tickLive,5000);
</script>
</body></html>"""
