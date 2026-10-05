#!/usr/bin/env python3
"""Stage 22 — drift-triggered threshold recalibration (LEVEL-UP).

Watches the false-positive-rate KPI the Lakebase layer already computes from real
reviewer outcomes (`resolved_items`). When an assay's FPR drifts above tolerance, it
opens a threshold-review task in `threshold_review_tasks` (operational, in Lakebase,
alongside the review queue) so a toxicologist is prompted to re-examine that assay's
deterministic thresholds. The deterministic flag stays the authority — this only
*flags the flagger for review* when reviewer outcomes say it is drifting.

Run:  python serving/drift_recalibration.py [--tolerance 0.20] [--min-resolved 3]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

sys.path.insert(0, "serving")
import lakebase  # noqa: E402

DDL = """
CREATE TABLE IF NOT EXISTS threshold_review_tasks (
  task_id           text PRIMARY KEY,
  assay_name        text NOT NULL,
  observed_fpr      double precision NOT NULL,
  n_resolved        integer NOT NULL,
  n_false_positive  integer NOT NULL,
  tolerance         double precision NOT NULL,
  status            text NOT NULL DEFAULT 'open',
  suggested_action  text,
  opened_ts         timestamptz NOT NULL DEFAULT now()
)
"""

FPR_BY_ASSAY = """
SELECT assay_name,
       count(*)                                                  AS n_resolved,
       count(*) FILTER (WHERE resolution_reason = 'false_positive') AS n_fp
FROM resolved_items
GROUP BY assay_name
ORDER BY assay_name
"""


def run(tolerance: float, min_resolved: int) -> int:
    conn = lakebase.get_connection()
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(DDL)
    cur.execute(FPR_BY_ASSAY)
    rows = cur.fetchall()

    print(f"drift check @ {dt.datetime.utcnow().isoformat()}Z  tolerance={tolerance:.0%}  min_resolved={min_resolved}")
    print(f"{'assay':14} {'n':>3} {'fp':>3} {'fpr':>6}  status")
    opened = 0
    for assay_name, n_resolved, n_fp in rows:
        fpr = (n_fp / n_resolved) if n_resolved else 0.0
        drifted = n_resolved >= min_resolved and fpr > tolerance
        status = "DRIFT -> open review task" if drifted else ("ok" if n_resolved >= min_resolved else "insufficient samples")
        print(f"{assay_name:14} {n_resolved:>3} {n_fp:>3} {fpr:>6.0%}  {status}")
        if drifted:
            task_id = f"tr-{assay_name}-{dt.date.today().isoformat()}"
            action = (f"Review {assay_name} deterministic threshold: {n_fp}/{n_resolved} "
                      f"recent flags were resolved as false positives (FPR {fpr:.0%} > {tolerance:.0%}).")
            cur.execute(
                """INSERT INTO threshold_review_tasks
                     (task_id, assay_name, observed_fpr, n_resolved, n_false_positive, tolerance, status, suggested_action)
                   VALUES (%s,%s,%s,%s,%s,%s,'open',%s)
                   ON CONFLICT (task_id) DO UPDATE SET
                     observed_fpr = EXCLUDED.observed_fpr, n_resolved = EXCLUDED.n_resolved,
                     n_false_positive = EXCLUDED.n_false_positive, suggested_action = EXCLUDED.suggested_action,
                     opened_ts = now(), status = 'open'""",
                (task_id, assay_name, fpr, n_resolved, n_fp, tolerance, action),
            )
            opened += 1

    cur.execute("SELECT task_id, assay_name, observed_fpr, status, suggested_action FROM threshold_review_tasks ORDER BY observed_fpr DESC")
    print(f"\nthreshold_review_tasks now open: {opened} opened/updated this run")
    for r in cur.fetchall():
        print(f"  [{r[3]}] {r[0]}  fpr={r[2]:.0%}\n         {r[4]}")
    conn.close()
    return opened


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tolerance", type=float, default=0.20)
    ap.add_argument("--min-resolved", type=int, default=3)
    args = ap.parse_args()
    run(args.tolerance, args.min_resolved)


# ============================================================================
#  VERIFIED RUN OUTPUT — captured live from workspace adb-7405610110498224
#  full capture: evidence/stage22-drift-recalibration-evidence.txt  |  notebooks/execution_evidence.ipynb (outputs committed)
# ============================================================================
# Stage 22 — drift-triggered threshold recalibration. Reads REAL reviewer outcomes from Lakebase resolved_items,
# opens a threshold-review task when an assay's false-positive rate drifts above tolerance.
#   real outcomes read: false_positive 4 | confirmed_concern 2 | escalated_for_confirmatory_assay 2 (8 total)
#   live run (--tolerance 0.20 --min-resolved 3):
#     CYP3A4_IC50  n=2 fp=1 fpr=50%  insufficient samples
#     LOGD_7_4     n=2 fp=1 fpr=50%  insufficient samples
#     hERG_IC50    n=4 fp=2 fpr=50%  DRIFT -> opened threshold_review_tasks row [tr-hERG_IC50-2026-09-25]
#   Low-sample assays (n<3) held as "insufficient samples" rather than firing on noise.
#   Keys off the SAME FPR KPI the Lakebase layer already computes; the deterministic flag stays the authority.
