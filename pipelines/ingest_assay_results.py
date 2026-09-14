"""Lakeflow Declarative Pipeline — raw LIMS ingestion into bronze.

Runs the custom `MockLimsLakeflowConnect` connector (which implements the
community-connectors `LakeflowConnect` interface) against the mock LIMS export
API and materializes the unmarshalled result as
`lead_opt_demo.bronze.assay_results_raw`.

The mock LIMS runs as a Databricks App. Its OAuth front door accepts U2M (user)
tokens but rejects M2M service-principal tokens (they 302 to login), so the
connector authenticates with a bearer read from a secret via dbutils.secrets
(NOT a `{{secrets/...}}` config reference — those come back redacted through
spark.conf.get). Plain (non-secret) pipeline `configuration` supplies:
  - mock_lims.host           : the mock LIMS base URL (the Databricks App)
  - mock_lims.api_key        : the vendor API key (X-API-Key)
  - mock_lims.token_url      : the workspace OIDC token endpoint
  - mock_lims.connector_path : where the connector package was synced
Secrets (scope `lead_opt`) read via dbutils.secrets.get:
  - mock_lims_bearer         : U2M bearer for the App (preferred)
  - ingest_sp_client_id / ingest_sp_secret : SP creds for the M2M fallback

connector.py is uploaded alongside this file so it is importable in-pipeline.
"""
import base64
import sys

import dlt
import requests
from pyspark.sql import SparkSession

spark = SparkSession.getActiveSession()

# The connector package is deployed as bundle files; its directory is passed in
# as a config value (resolved from ${workspace.file_path} by the asset bundle).
_connector_path = spark.conf.get("mock_lims.connector_path", "")
if _connector_path and _connector_path not in sys.path:
    sys.path.append(_connector_path)

from connector import MockLimsLakeflowConnect  # noqa: E402

TABLE = "assay_results"
SECRET_SCOPE = "lead_opt"


def _secret(key: str) -> str:
    """Read a secret's real value (spark.conf `{{secrets/...}}` comes back redacted)."""
    try:
        return dbutils.secrets.get(SECRET_SCOPE, key)  # noqa: F821  (dbutils is injected)
    except Exception:
        return ""


def _oauth_bearer() -> str:
    """Bearer for reaching the mock LIMS Databricks App.

    Databricks Apps' OAuth front door accepts U2M (user) tokens but currently
    rejects M2M service-principal tokens (they 302 to login). So prefer an
    explicit U2M bearer from the secret scope (valid well beyond a run's
    duration); fall back to minting a service-principal M2M token for the day
    Apps accept them or when the source is not App-fronted.
    """
    explicit = _secret("mock_lims_bearer")
    if explicit:
        return explicit
    client_id = _secret("ingest_sp_client_id")
    client_secret = _secret("ingest_sp_secret")
    token_url = spark.conf.get("mock_lims.token_url")
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    resp = requests.post(
        token_url,
        headers={"Authorization": f"Basic {basic}"},
        data={"grant_type": "client_credentials", "scope": "all-apis"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _connector() -> MockLimsLakeflowConnect:
    return MockLimsLakeflowConnect({
        "host": spark.conf.get("mock_lims.host"),
        "api_key": spark.conf.get("mock_lims.api_key", "lims-demo-key"),
        "bearer_token": _oauth_bearer(),
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


def _to_dataframe(rows, schema):
    """Build a DataFrame at the connector's declared schema.

    The connector emits JSON-compatible values (per the LakeflowConnect
    contract): timestamps arrive as ISO strings, not datetime objects, so
    createDataFrame can't accept them directly against a TimestampType field.
    Stage the timestamp fields as strings, then cast to the declared type —
    the same string->type coercion the framework's own ingest() would do.
    """
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
    return _to_dataframe(rows, schema)
