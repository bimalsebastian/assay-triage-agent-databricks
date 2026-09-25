# Custom Lakeflow connectors — reusable reference pattern

Two custom [Lakeflow](https://docs.databricks.com/aws/en/ingestion/) connectors
live here. They exist to do the one thing a *managed* connector can't: take a
vendor's awkward export envelope and unmarshal it into a clean, typed schema for
a bronze Delta table — with the parsing logic pure and unit-testable off-Spark.

Treat this as a **reference implementation** you can lift for any messy source
(a LIMS/CDR export, a legacy REST API, a partner feed). The shape generalises;
only the field mapping is domain-specific.

| Connector | Source | Envelope quirks it handles |
|-----------|--------|----------------------------|
| `mock_lims/connector.py` | LIMS assay-results export (Databricks App) | records nested under `LIMS_EXPORT.resultSet.records`, abbreviated field names (`smpl`, `analyte`, `meas.val`), non-ISO timestamp `'20260912 04:09:15.558'`, compound id buried in a composite sample id `LO-CMPD00042-P3-B07-R2` |
| `mock_ehr/connector.py` | openEHR CDR queried via **AQL** over REST | hierarchical compositions, AQL result rows → flat clinical bronze |

## The pattern (why it's shaped this way)

1. **Pure parsing functions at module scope, framework glue in the class.**
   `parse_sample_id`, `parse_lims_timestamp`, `parse_float`, `unmarshal_record`
   take/return plain dicts and import nothing heavy — so they run in
   `tests/test_connector_local.py` **without a Spark session**. Only
   `get_table_schema` needs `pyspark`, and it imports it lazily. This is the
   single biggest reusability win: your transformation logic is testable in
   milliseconds, in CI, with no cluster.

2. **Never drop a row on a parse miss.** `parse_sample_id` keeps the raw id and
   leaves derived fields null rather than discarding the record — bronze stays a
   faithful landing zone; quality gating happens later in silver.

3. **Implement the `LakeflowConnect` interface** from
   `databricks-labs-community-connector`:
   - `list_tables()` — enumerate source objects
   - `get_table_schema()` — the clean, typed target schema
   - `read_table_metadata()` — primary keys, cursor field, ingestion type
   - `read_table(start_offset, ...)` — page the source, yield unmarshalled
     records, and return the advanced offset (empty page ⇒ offset unchanged ⇒
     the framework stops). This is how incremental/snapshot paging works.

4. **Auth is injected, never hardcoded.** `options` carries `host` (the source
   base URL), an `api_key`, and an optional Databricks OAuth `bearer_token` the
   pipeline supplies from the secret scope — see `pipelines/ingest_*.py`
   (`SECRET_SCOPE = "lead_opt"`). Swap in an M2M service-principal token for
   production.

## Reuse checklist

To adapt for a new source, you typically only change:
- the envelope path in `read_table()` / `list_tables()`,
- the `unmarshal_record()` field mapping,
- the `get_table_schema()` struct,
- the `_SAMPLE_RE` (or any source-specific id/timestamp parsing).

Keep the pure-function + lazy-pyspark split and the "don't drop rows" rule, and
the connector stays testable and bronze-safe.

## Tests

`tests/test_connector_local.py` exercises the parsing functions directly (happy
path + malformed ids + bad timestamps) with no Spark. Run:

```bash
python -m pytest tests/test_connector_local.py -q
```

Data is entirely **synthetic**, produced by the mock LIMS/EHR services — no real
compounds, patients, or customer identifiers.
