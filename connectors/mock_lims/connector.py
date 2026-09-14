"""Custom Lakeflow connector for the mock LIMS export API.

Implements the `LakeflowConnect` interface from
`databricks-labs-community-connector`. Its job is exactly the thing a managed
connector can't do: take the vendor's awkward export envelope — records nested
under `LIMS_EXPORT.resultSet.records`, abbreviated field names, a non-ISO
timestamp, and a compound ID buried inside a composite sample ID — and
unmarshal it into a clean, typed, defined schema for the bronze table.

The pure parsing logic lives in module-level functions so it can be unit-tested
without a Spark session (see tests/test_connector_local.py). Only
`get_table_schema` needs pyspark, and it imports it lazily.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterator

import requests

try:  # framework is present in the pipeline environment, not needed for parsing tests
    from databricks.labs.community_connector.interface.lakeflow_connect import (
        LakeflowConnect,
    )
except Exception:  # pragma: no cover - local fallback so the module imports anywhere
    class LakeflowConnect:  # minimal shim mirroring the real ABC
        def __init__(self, options: dict[str, str]) -> None:
            self.options = options


TABLE = "assay_results"
PAGE_SIZE = 200

# LO-CMPD00042-P3-B07-R2 -> compound CMPD00042, plate P3, well B07, replicate 2
_SAMPLE_RE = re.compile(
    r"^LO-(?P<compound>CMPD\d{5})-P(?P<plate>\d+)-(?P<well>[A-H]\d{2})-R(?P<rep>\d+)$"
)


def parse_sample_id(sample_id: str) -> dict:
    """Split the composite LIMS sample ID into its parts."""
    m = _SAMPLE_RE.match(sample_id or "")
    if not m:
        # Keep the raw id; leave derived fields null rather than dropping the row.
        return {"compound_id": None, "plate": None, "well": None, "replicate": None}
    return {
        "compound_id": m.group("compound"),
        "plate": f"P{m.group('plate')}",
        "well": m.group("well"),
        "replicate": int(m.group("rep")),
    }


def parse_lims_timestamp(raw: str) -> str | None:
    """'20260912 04:09:15.558' (non-ISO) -> '2026-09-12 04:09:15.558' (Spark-castable)."""
    if not raw:
        return None
    try:
        dt = datetime.strptime(raw, "%Y%m%d %H:%M:%S.%f")
    except ValueError:
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def parse_float(raw) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def unmarshal_record(rec: dict) -> dict:
    """Awkward vendor record -> one clean, flat, typed-ready dict."""
    parts = parse_sample_id(rec.get("smpl"))
    meas = rec.get("meas") or {}
    return {
        "sample_id": rec.get("smpl"),
        "compound_id": parts["compound_id"],
        "plate": parts["plate"],
        "well": parts["well"],
        "replicate": parts["replicate"],
        "assay_name": rec.get("analyte"),
        "result_value": parse_float(meas.get("val")),
        "result_unit": meas.get("uom"),
        "acquired_ts": parse_lims_timestamp(rec.get("acqTs")),
        "assay_protocol": rec.get("proto"),
        "operator_id": rec.get("operator"),
        "batch_guid": rec.get("batchGuid"),
        "qc_flag": rec.get("qcFlag"),
    }


class MockLimsLakeflowConnect(LakeflowConnect):
    """LakeflowConnect implementation for the mock LIMS assay-results export."""

    def __init__(self, options: dict[str, str]) -> None:
        super().__init__(options)
        # Injected from the Unity Catalog connection (host + bearer), plus the
        # vendor API key. `host` is the mock LIMS base URL (the Databricks App).
        self.base_url = (options.get("host") or options.get("base_url") or "").rstrip("/")
        self.api_key = options.get("api_key") or options.get("lims_api_key") or "lims-demo-key"
        # Optional Databricks OAuth bearer for reaching the App (set by pipeline).
        self.bearer = options.get("bearer_token")
        if not self.base_url:
            raise ValueError("mock LIMS connector requires a 'host' option (base URL)")

    # -- HTTP -----------------------------------------------------------------
    def _headers(self) -> dict:
        h = {"X-API-Key": self.api_key, "Accept": "application/json"}
        if self.bearer:
            h["Authorization"] = f"Bearer {self.bearer}"
        return h

    def _get(self, path: str, params: dict | None = None) -> dict:
        resp = requests.get(
            f"{self.base_url}{path}", headers=self._headers(),
            params=params or {}, timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # -- LakeflowConnect interface -------------------------------------------
    def list_tables(self) -> list[str]:
        body = self._get("/lims/v1/objects")
        objs = body.get("LIMS_EXPORT", {}).get("objects", [])
        return [o["name"] for o in objs]

    def get_table_schema(self, table_name: str, table_options: dict[str, str]):
        from pyspark.sql.types import (
            DoubleType, IntegerType, StringType, StructField, StructType,
            TimestampType,
        )
        return StructType([
            StructField("sample_id", StringType(), False),
            StructField("compound_id", StringType(), True),
            StructField("plate", StringType(), True),
            StructField("well", StringType(), True),
            StructField("replicate", IntegerType(), True),
            StructField("assay_name", StringType(), True),
            StructField("result_value", DoubleType(), True),
            StructField("result_unit", StringType(), True),
            StructField("acquired_ts", TimestampType(), True),
            StructField("assay_protocol", StringType(), True),
            StructField("operator_id", StringType(), True),
            StructField("batch_guid", StringType(), True),
            StructField("qc_flag", StringType(), True),
        ])

    def read_table_metadata(self, table_name: str, table_options: dict[str, str]) -> dict:
        return {
            "primary_keys": ["sample_id", "assay_name"],
            "cursor_field": "acquired_ts",
            "ingestion_type": "snapshot",
        }

    def read_table(
        self, table_name: str, start_offset: dict, table_options: dict[str, str]
    ) -> tuple[Iterator[dict], dict]:
        offset = (start_offset or {}).get("offset", 0)
        body = self._get(
            f"/lims/v1/export/{table_name}",
            params={"offset": offset, "limit": PAGE_SIZE},
        )
        rs = body.get("LIMS_EXPORT", {}).get("resultSet", {})
        raw = rs.get("records", [])
        records = (unmarshal_record(r) for r in raw)
        # offset advances by the page size actually returned; when a page comes
        # back empty the offset is unchanged and the framework stops.
        end_offset = {"offset": offset + len(raw)}
        return records, end_offset
