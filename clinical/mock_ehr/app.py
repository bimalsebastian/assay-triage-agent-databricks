"""Mock openEHR Clinical Data Repository — AQL REST surface.

Speaks a faithful subset of EHRbase's AQL REST contract: a client POSTs an AQL
query and gets back an openEHR RESULTSET ({columns, rows}). It stands in for a
real EHRbase CDR (which would run in Docker with a real openEHR RM / archetype /
template / AQL engine) so the ingestion can run as a real Databricks serverless
Lakeflow pipeline reachable from the workspace — see GOVERNANCE/DESIGN notes.
It does NOT validate AQL against a real archetype model; it projects the planted
synthetic compositions into the requested resultset shape.

Deployed as a Databricks App (behind workspace OAuth); an X-API-Key header adds
a vendor-style application check on top.
"""
from __future__ import annotations

import os

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse

from synth_ehr import COLUMNS, generate_rows

API_KEY = os.environ.get("EHR_API_KEY", "ehr-demo-key")

app = FastAPI(title="Mock openEHR CDR (AQL)", version="1.0.0")

_ROWS = generate_rows()


def _check_key(x_api_key: str | None) -> None:
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


@app.get("/ehrbase/rest/status")
def status() -> dict:
    return {"status": "ok", "compositions": len(_ROWS)}


@app.post("/ehrbase/rest/openehr/v1/query/aql")
async def query_aql(request: Request, x_api_key: str | None = Header(default=None)):
    """AQL query endpoint. Returns an openEHR RESULTSET. The mock projects the
    synthetic compositions into COLUMNS; it honours LIMIT/OFFSET if present in
    the request body but does not otherwise interpret the AQL."""
    _check_key(x_api_key)
    body = await request.json()
    q = (body.get("q") or body.get("query") or "").strip()
    limit = body.get("limit")
    offset = body.get("offset") or 0
    rows = _ROWS[offset:(offset + limit) if limit else None]
    return {
        "meta": {"_type": "RESULTSET", "_executed_aql": q},
        "q": q,
        "columns": [{"name": c, "path": f"/content/{c}"} for c in COLUMNS],
        "rows": [[r[c] for c in COLUMNS] for r in rows],
    }


@app.get("/", response_class=HTMLResponse)
def landing() -> str:
    patients = sorted({r["patient_ref"] for r in _ROWS})
    drugs = sorted({r["drug_code"] for r in _ROWS})
    otypes = sorted({r["observation_type"] for r in _ROWS})
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Mock openEHR CDR</title>
<style>body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f6f7f9;
color:#1b1f24;margin:0}}main{{max-width:640px;margin:40px auto;padding:0 20px}}
.card{{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:20px 24px}}
h1{{font-size:19px;margin:0 0 4px}}.muted{{color:#8a97a5;font-size:13px}}
.stat{{display:inline-block;margin:14px 24px 6px 0}}.n{{font-size:26px;font-weight:700;color:#0b3d2e}}
code{{background:#eef1f4;padding:1px 6px;border-radius:4px;font-size:12px}}</style>
</head><body><main><div class="card">
<h1>Mock openEHR CDR (AQL)</h1>
<div class="muted">Synthetic openEHR compositions, queried over an AQL REST
surface. Stands in for a real EHRbase CDR so ingestion can run as a Databricks
pipeline. All patient data is synthetic — no names, DOBs, or real identifiers.</div>
<div>
 <div class="stat"><div class="n">{len(_ROWS)}</div><div class="muted">compositions</div></div>
 <div class="stat"><div class="n">{len(patients)}</div><div class="muted">synthetic patients</div></div>
 <div class="stat"><div class="n">{len(drugs)}</div><div class="muted">drug codes</div></div>
</div>
<p class="muted">observation types: {', '.join(otypes)}<br>
AQL endpoint: <code>POST /ehrbase/rest/openehr/v1/query/aql</code> (needs
<code>X-API-Key</code>). Status: <code>/ehrbase/rest/status</code>.</p>
</div></main></body></html>"""
