"""Local end-to-end test: drive the custom connector against the running mock
LIMS and verify pagination + awkward->clean unmarshalling. No Spark needed.

Run the mock LIMS first (uvicorn app:app on :8123), then:
    python tests/test_connector_local.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "connectors", "mock_lims"))

from connector import MockLimsLakeflowConnect  # noqa: E402

BASE = os.environ.get("LIMS_BASE_URL", "http://127.0.0.1:8123")


def read_all(conn, table):
    """Replicate the framework's read loop: call until offset stops advancing."""
    rows, offset = [], None
    while True:
        batch, end = conn.read_table(table, offset, {})
        batch = list(batch)
        rows.extend(batch)
        if end == offset or not batch:
            break
        offset = end
    return rows


def main():
    conn = MockLimsLakeflowConnect({"host": BASE, "api_key": "lims-demo-key"})

    tables = conn.list_tables()
    assert tables == ["assay_results"], tables
    print(f"list_tables() -> {tables}")

    meta = conn.read_table_metadata("assay_results", {})
    print(f"read_table_metadata() -> {meta}")

    rows = read_all(conn, "assay_results")
    print(f"read_table() paginated -> {len(rows)} clean records")

    # Parsing assertions on real data pulled through the HTTP API.
    sample = rows[0]
    assert set(sample) >= {
        "sample_id", "compound_id", "plate", "well", "replicate",
        "assay_name", "result_value", "result_unit", "acquired_ts",
    }, sample
    assert all(r["compound_id"] and r["compound_id"].startswith("CMPD") for r in rows), \
        "compound_id must be extracted from the composite sample_id"
    assert all(isinstance(r["result_value"], float) for r in rows), \
        "result_value must be parsed string->float"
    assert all(r["acquired_ts"] and r["acquired_ts"][4] == "-" for r in rows), \
        "acquired_ts must be reformatted to ISO (YYYY-MM-DD ...)"
    assert all(isinstance(r["replicate"], int) for r in rows), \
        "replicate must be parsed to int"

    n_compounds = len({r["compound_id"] for r in rows})
    n_low_herg = sum(
        1 for r in rows if r["assay_name"] == "hERG_IC50" and r["result_value"] < 1.0
    )
    print(f"distinct compounds: {n_compounds}")
    print(f"hERG_IC50 readings below 1.0 uM (future tox flags): {n_low_herg}")
    print("\nsample clean records:")
    for r in rows[:3]:
        print("  ", r)
    print("\nALL LOCAL CONNECTOR ASSERTIONS PASSED")


if __name__ == "__main__":
    main()
