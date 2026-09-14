"""Sync job: refresh the Lakebase review_queue from Delta assay_flags.

Reads the current open flags (is_flagged = true) from the governed silver
assay_flags table, upserts them into Lakebase (preserving any reviewer
resolution), and clears queue items that are no longer flagged upstream. Can be
run standalone or called at the tail of the stage-02 batch.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from dbsql import query_rows  # noqa: E402

import lakebase  # noqa: E402

SOURCE_QUERY = """
    SELECT reading_id, compound_id, assay_name, result_value, result_unit,
           concern_direction, threshold, threshold_unit, margin,
           compound_prior_n, compound_prior_mean, reason,
           cast(evaluated_ts AS STRING) AS flagged_ts
    FROM lead_opt_demo.silver.assay_flags
    WHERE is_flagged = true
"""


def sync() -> dict:
    rows = query_rows(SOURCE_QUERY)
    upserted = lakebase.upsert_flags(rows)
    cleared = lakebase.clear_stale([r["reading_id"] for r in rows])
    summary = lakebase.get_queue_summary()
    return {"source_open_flags": len(rows), "upserted": upserted,
            "cleared_stale": cleared, "queue_by_status": summary}


if __name__ == "__main__":
    result = sync()
    print("sync complete:")
    for k, v in result.items():
        print(f"  {k}: {v}")
