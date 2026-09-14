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
    SELECT af.reading_id, af.compound_id, af.assay_name, af.result_value, af.result_unit,
           af.concern_direction, af.threshold, af.threshold_unit, af.margin,
           af.compound_prior_n, af.compound_prior_mean, af.reason,
           cast(af.evaluated_ts AS STRING) AS flagged_ts,
           afc.correlation_state AS clinical_correlation_state,
           afc.drug_code AS clinical_drug_code,
           afc.signal_detail AS clinical_signal_detail
    FROM lead_opt_demo.silver.assay_flags af
    LEFT JOIN lead_opt_demo.silver.assay_flags_clinical afc
      ON afc.compound_id = af.compound_id
    WHERE af.is_flagged = true
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
