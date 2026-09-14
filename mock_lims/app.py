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

from fastapi import FastAPI, Header, HTTPException, Query

from synth import generate_records

API_KEY = os.environ.get("LIMS_API_KEY", "lims-demo-key")

app = FastAPI(title="Mock LIMS Export API", version="1.0.0")

# Generate once at startup; served stably thereafter.
_RECORDS = generate_records()


def _check_key(x_api_key: str | None) -> None:
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


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
