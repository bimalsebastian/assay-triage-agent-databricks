"""Mock LIMS assay-results export API.

Simulates a vendor LIMS export endpoint: the payload is deliberately awkward
(records nested under a vendor key, abbreviated field names, non-ISO
timestamps, compound ID buried inside a composite sample ID). A managed
connector wouldn't handle this shape — which is the whole point of building a
custom Lakeflow connector against it.

Runs locally with `uvicorn app:app` and unchanged as a Databricks App
(see app.yaml). Application-layer auth is a simple X-API-Key header, the kind
of vendor API key a real LIMS export would issue; when deployed as a Databricks
App it additionally sits behind the workspace's OAuth.
"""
from __future__ import annotations

import os
import re

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse

from synth import generate_records

API_KEY = os.environ.get("LIMS_API_KEY", "lims-demo-key")

app = FastAPI(title="Mock LIMS Export API", version="1.0.0")

# Generate once at startup; served stably thereafter.
_RECORDS = generate_records()

# Lightweight stats for the landing page.
_COMPOUNDS = sorted({m.group(1) for r in _RECORDS
                     if (m := re.match(r"LO-(CMPD\d+)", r.get("smpl", "")))})
_ANALYTES = sorted({r.get("analyte") for r in _RECORDS})


def _check_key(x_api_key: str | None) -> None:
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


@app.get("/", response_class=HTMLResponse)
def landing() -> str:
    """Tiny status page. This service is a headless data source for the Lakeflow
    connector; the real payload lives under /lims/v1/export/{object} (API key
    required). See /docs for an interactive explorer."""
    rows = "".join(f"<tr><td>{a}</td></tr>" for a in _ANALYTES)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Mock LIMS Export API</title>
<style>body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f6f7f9;
color:#1b1f24;margin:0}}main{{max-width:640px;margin:40px auto;padding:0 20px}}
.card{{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:20px 24px}}
h1{{font-size:19px;margin:0 0 4px}}.muted{{color:#8a97a5;font-size:13px}}
.stat{{display:inline-block;margin:14px 24px 6px 0}}.n{{font-size:26px;font-weight:700;color:#0b3d2e}}
table{{border-collapse:collapse;font-size:13px;margin-top:8px}}td{{border-bottom:1px solid #eef1f4;padding:4px 10px}}
code{{background:#eef1f4;padding:1px 6px;border-radius:4px;font-size:12px}}a{{color:#0b3d2e}}</style>
</head><body><main><div class="card">
<h1>Mock LIMS Export API</h1>
<div class="muted">Synthetic vendor LIMS assay-results export — the data source the
custom Lakeflow connector ingests from. Not a user app; no personal data.</div>
<div>
 <div class="stat"><div class="n">{len(_RECORDS)}</div><div class="muted">assay readings</div></div>
 <div class="stat"><div class="n">{len(_COMPOUNDS)}</div><div class="muted">compounds</div></div>
 <div class="stat"><div class="n">{len(_ANALYTES)}</div><div class="muted">assay types</div></div>
</div>
<table><tr><td class="muted">assay types</td></tr>{rows}</table>
<p class="muted" style="margin-top:16px">Endpoints (require <code>X-API-Key</code>):
<code>/lims/v1/objects</code>, <code>/lims/v1/export/assay_results</code>.
Health: <code>/health</code>. Interactive: <a href="docs">/docs</a>.</p>
</div></main></body></html>"""


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "records": len(_RECORDS)}


@app.get("/lims/v1/objects")
def list_objects(x_api_key: str | None = Header(default=None)) -> dict:
    """Vendor 'catalog' endpoint: which export objects exist."""
    _check_key(x_api_key)
    return {
        "LIMS_EXPORT": {
            "objects": [
                {"name": "assay_results", "recordCount": len(_RECORDS)},
            ]
        }
    }


@app.get("/lims/v1/export/{object_name}")
def export_object(
    object_name: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    x_api_key: str | None = Header(default=None),
) -> dict:
    """Paginated export of an object, in the vendor's nested envelope."""
    _check_key(x_api_key)
    if object_name != "assay_results":
        raise HTTPException(status_code=404, detail=f"unknown object {object_name}")

    window = _RECORDS[offset : offset + limit]
    next_offset = offset + len(window)
    has_more = next_offset < len(_RECORDS)
    return {
        "LIMS_EXPORT": {
            "exportedAt": "20260914 09:00:00.000",  # non-ISO, matches record fmt
            "object": object_name,
            "resultSet": {
                "totalCount": len(_RECORDS),
                "returned": len(window),
                "offset": offset,
                "nextOffset": next_offset if has_more else None,
                "records": window,
            },
        }
    }
