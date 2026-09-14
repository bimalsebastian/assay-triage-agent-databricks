"""Custom Lakeflow connector for the mock openEHR CDR (AQL over REST).

Same LakeflowConnect interface/pattern as the stage-00 LIMS connector, but the
read logic issues an AQL query against the CDR's REST API and flattens the
returned openEHR RESULTSET (columns + rows) into a clean schema:
patient_ref, drug_code, observation_type, value, effective_ts.
"""
from __future__ import annotations

from typing import Iterator

import requests

try:
    from databricks.labs.community_connector.interface.lakeflow_connect import (
        LakeflowConnect,
    )
except Exception:  # pragma: no cover - local fallback
    class LakeflowConnect:
        def __init__(self, options: dict[str, str]) -> None:
            self.options = options


TABLE = "ehr_compositions"
PAGE_SIZE = 500
AQL = (
    "SELECT c/patient_ref, c/drug_code, c/observation_type, c/value, "
    "c/effective_ts FROM EHR e CONTAINS COMPOSITION c ORDER BY c/effective_ts"
)


class MockEhrLakeflowConnect(LakeflowConnect):
    """LakeflowConnect implementation over the mock openEHR CDR's AQL endpoint."""

    def __init__(self, options: dict[str, str]) -> None:
        super().__init__(options)
        self.base_url = (options.get("host") or options.get("base_url") or "").rstrip("/")
        self.api_key = options.get("api_key") or options.get("ehr_api_key") or "ehr-demo-key"
        self.bearer = options.get("bearer_token")
        if not self.base_url:
            raise ValueError("mock EHR connector requires a 'host' option (base URL)")

    def _headers(self) -> dict:
        h = {"X-API-Key": self.api_key, "Accept": "application/json",
             "Content-Type": "application/json"}
        if self.bearer:
            h["Authorization"] = f"Bearer {self.bearer}"
        return h

    def _aql(self, offset: int, limit: int) -> dict:
        resp = requests.post(
            f"{self.base_url}/ehrbase/rest/openehr/v1/query/aql",
            headers=self._headers(),
            json={"q": AQL, "offset": offset, "limit": limit},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def list_tables(self) -> list[str]:
        return [TABLE]

    def get_table_schema(self, table_name: str, table_options: dict[str, str]):
        from pyspark.sql.types import (
            StringType, StructField, StructType, TimestampType,
        )
        return StructType([
            StructField("patient_ref", StringType(), False),
            StructField("drug_code", StringType(), True),
            StructField("observation_type", StringType(), True),
            StructField("value", StringType(), True),
            StructField("effective_ts", TimestampType(), True),
        ])

    def read_table_metadata(self, table_name: str, table_options: dict[str, str]) -> dict:
        return {
            "primary_keys": ["patient_ref", "drug_code", "observation_type", "effective_ts"],
            "cursor_field": "effective_ts",
            "ingestion_type": "snapshot",
        }

    def read_table(
        self, table_name: str, start_offset: dict, table_options: dict[str, str]
    ) -> tuple[Iterator[dict], dict]:
        offset = (start_offset or {}).get("offset", 0)
        body = self._aql(offset, PAGE_SIZE)
        cols = [c["name"] for c in body.get("columns", [])]
        rows = body.get("rows", [])
        records = (dict(zip(cols, row)) for row in rows)
        return records, {"offset": offset + len(rows)}
