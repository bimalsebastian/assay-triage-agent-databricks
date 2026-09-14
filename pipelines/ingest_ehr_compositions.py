"""Lakeflow Declarative Pipeline — clinical openEHR ingestion into bronze.

Runs the custom MockEhrLakeflowConnect connector (AQL over the mock openEHR
CDR's REST API) and materializes the flattened compositions as
lead_opt_demo_clinical.bronze.ehr_compositions_raw — a distinct catalog from
the preclinical one, per CLAUDE.md's clinical governance note.

Same auth pattern as the stage-00 LIMS pipeline: the CDR runs as a Databricks
App (OAuth front door, rejects M2M SP tokens), so the connector uses a U2M
bearer read via dbutils.secrets.get. Plain config supplies host/api_key/
connector_path.
"""
import sys

import dlt
from pyspark.sql import SparkSession

spark = SparkSession.getActiveSession()

_connector_path = spark.conf.get("mock_ehr.connector_path", "")
if _connector_path and _connector_path not in sys.path:
    sys.path.append(_connector_path)

from connector import MockEhrLakeflowConnect  # noqa: E402

TABLE = "ehr_compositions"
SECRET_SCOPE = "lead_opt"


def _connector() -> MockEhrLakeflowConnect:
    try:
        bearer = dbutils.secrets.get(SECRET_SCOPE, "mock_ehr_bearer")  # noqa: F821
    except Exception:
        bearer = ""
    return MockEhrLakeflowConnect({
        "host": spark.conf.get("mock_ehr.host"),
        "api_key": spark.conf.get("mock_ehr.api_key", "ehr-demo-key"),
        "bearer_token": bearer,
    })


def _read_all(conn) -> list[dict]:
    rows, offset = [], None
    while True:
        batch, end = conn.read_table(TABLE, offset, {})
        batch = list(batch)
        rows.extend(batch)
        if end == offset or not batch:
            break
        offset = end
    return rows


def _to_dataframe(rows, schema):
    from pyspark.sql import functions as F
    from pyspark.sql.types import StringType, StructField, StructType, TimestampType
    ts_fields = {f.name for f in schema.fields if isinstance(f.dataType, TimestampType)}
    staging = StructType([
        StructField(f.name, StringType() if f.name in ts_fields else f.dataType, True)
        for f in schema.fields
    ])
    df = spark.createDataFrame(rows, staging)
    for name in ts_fields:
        df = df.withColumn(name, F.col(name).cast(TimestampType()))
    return df.select([f.name for f in schema.fields])


@dlt.table(
    name="ehr_compositions_raw",
    comment="Raw synthetic openEHR compositions ingested from the mock CDR via "
            "the custom AQL Lakeflow connector. Clinical bronze (stage 07) — "
            "distinct catalog, tighter governance downstream.",
    table_properties={"quality": "bronze", "pipelines.reset.allowed": "true"},
)
def ehr_compositions_raw():
    conn = _connector()
    schema = conn.get_table_schema(TABLE, {})
    return _to_dataframe(_read_all(conn), schema)
