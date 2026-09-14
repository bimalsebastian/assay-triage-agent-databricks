"""Lakeflow Declarative Pipeline — raw LIMS ingestion into bronze.

Runs the custom `MockLimsLakeflowConnect` connector (which implements the
community-connectors `LakeflowConnect` interface) against the mock LIMS export
API and materializes the unmarshalled result as
`lead_opt_demo.bronze.assay_results_raw`.

The pipeline is configured (see the pipeline's `configuration`) with:
  - mock_lims.host    : the mock LIMS base URL (the Databricks App)
  - mock_lims.api_key : the vendor API key (X-API-Key)
  - mock_lims.bearer  : a Databricks OAuth/PAT bearer with access to the App,
                        supplied via a secret reference so it is not inlined.

connector.py is uploaded alongside this file so it is importable in-pipeline.
"""
import dlt
from pyspark.sql import SparkSession

from connector import MockLimsLakeflowConnect

spark = SparkSession.getActiveSession()

TABLE = "assay_results"


def _connector() -> MockLimsLakeflowConnect:
    return MockLimsLakeflowConnect({
        "host": spark.conf.get("mock_lims.host"),
        "api_key": spark.conf.get("mock_lims.api_key", "lims-demo-key"),
        "bearer_token": spark.conf.get("mock_lims.bearer", ""),
    })


def _read_all(conn) -> list[dict]:
    """Drive the LakeflowConnect pagination protocol to exhaustion."""
    rows, offset = [], None
    while True:
        batch, end = conn.read_table(TABLE, offset, {})
        batch = list(batch)
        rows.extend(batch)
        if end == offset or not batch:
            break
        offset = end
    return rows


@dlt.table(
    name="assay_results_raw",
    comment="Raw assay readings ingested from the mock LIMS via the custom "
            "Lakeflow connector; awkward vendor payload unmarshalled to a "
            "clean typed schema. Stage 00 bronze — do not hand-seed.",
    table_properties={"quality": "bronze", "pipelines.reset.allowed": "true"},
)
def assay_results_raw():
    conn = _connector()
    schema = conn.get_table_schema(TABLE, {})
    rows = _read_all(conn)
    return spark.createDataFrame(rows, schema)
