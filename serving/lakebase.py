"""Lakebase access layer for the review queue.

The app (stage 05) and the sync job import this instead of scattering raw SQL.
Connection params come from the environment first (PGHOST/PGUSER/PGPASSWORD/
PGDATABASE) — that is how the Databricks App injects its own OAuth-backed
credentials — and fall back to the Databricks CLI for local runs.

Lakebase OAuth tokens expire after ~1h, so a fresh token is fetched per
get_connection() call in the CLI fallback path.
"""
from __future__ import annotations

import json
import os
import subprocess

import psycopg2
from psycopg2.extras import RealDictCursor, execute_values

PROJECT = "lead-opt-triage"
BRANCH = "production"
ENDPOINT = "primary"
DBNAME = "lead_opt"
PROFILE = os.environ.get("DATABRICKS_CONFIG_PROFILE", "adb-7405610110498224")


def _cli_json(args: list[str]):
    out = subprocess.run(
        ["databricks", *args, "--profile", PROFILE, "--output", "json"],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


def _conn_params() -> dict:
    host = os.environ.get("PGHOST")
    user = os.environ.get("PGUSER")
    password = os.environ.get("PGPASSWORD")
    database = os.environ.get("PGDATABASE", DBNAME)
    if not host:
        eps = _cli_json(["postgres", "list-endpoints", f"projects/{PROJECT}/branches/{BRANCH}"])
        host = eps[0]["status"]["hosts"]["host"]
    if not password:
        cred = _cli_json(["postgres", "generate-database-credential",
                          f"projects/{PROJECT}/branches/{BRANCH}/endpoints/{ENDPOINT}"])
        password = cred["token"]
    if not user:
        user = _cli_json(["current-user", "me"])["userName"]
    return {"host": host, "port": 5432, "dbname": database,
            "user": user, "password": password, "sslmode": "require"}


_CRED_PROVIDER = None


def set_credential_provider(fn):
    """Override how connection params are obtained (dict with host/port/dbname/
    user/password/sslmode). The long-running app uses this to supply a freshly
    minted OAuth token per connection (Lakebase tokens expire ~1h)."""
    global _CRED_PROVIDER
    _CRED_PROVIDER = fn


def get_connection():
    params = _CRED_PROVIDER() if _CRED_PROVIDER else _conn_params()
    return psycopg2.connect(**params)


def get_review_queue(status: str = "open", limit: int | None = None) -> list[dict]:
    """Current review queue rows (default: open items), newest flags first."""
    sql = """
        SELECT reading_id, compound_id, assay_name, result_value, result_unit,
               concern_direction, threshold, threshold_unit, margin,
               compound_prior_n, compound_prior_mean, reason, status,
               flagged_ts, synced_ts, resolved_by, resolved_ts, resolution_note
        FROM review_queue
        {where}
        ORDER BY margin ASC NULLS LAST, compound_id
        {limit}
    """.format(
        where="WHERE status = %(status)s" if status else "",
        limit="LIMIT %(limit)s" if limit else "",
    )
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, {"status": status, "limit": limit})
        return [dict(r) for r in cur.fetchall()]


def get_queue_summary() -> dict:
    """Count of items by status."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT status, count(*) FROM review_queue GROUP BY status ORDER BY status")
        return {row[0]: row[1] for row in cur.fetchall()}


RESOLUTION_REASONS = (
    "false_positive", "confirmed_concern", "escalated_for_confirmatory_assay",
)


def resolve_item(reading_id: str, resolved_by: str, resolution_reason: str,
                 note: str | None = None) -> bool:
    """Resolve a queued item with a required reason.

    Records the resolution in resolved_items (which powers the flag->resolve KPI
    and survives after the row leaves the active queue) and marks the review_queue
    row resolved. The reason must be one of RESOLUTION_REASONS.
    """
    if resolution_reason not in RESOLUTION_REASONS:
        raise ValueError(f"resolution_reason must be one of {RESOLUTION_REASONS}")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO resolved_items (
                   reading_id, compound_id, assay_name, result_value, result_unit,
                   threshold, margin, reason, resolution_reason, resolved_by,
                   resolved_ts, flagged_ts, resolution_note)
               SELECT reading_id, compound_id, assay_name, result_value, result_unit,
                      threshold, margin, reason, %s, %s, now(), flagged_ts, %s
                 FROM review_queue
                WHERE reading_id = %s AND status = 'open'
               ON CONFLICT (reading_id) DO NOTHING""",
            (resolution_reason, resolved_by, note, reading_id),
        )
        inserted = cur.rowcount
        cur.execute(
            """UPDATE review_queue
                 SET status = 'resolved', resolved_by = %s, resolved_ts = now(),
                     resolution_reason = %s, resolution_note = %s
               WHERE reading_id = %s AND status = 'open'""",
            (resolved_by, resolution_reason, note, reading_id),
        )
        conn.commit()
        return inserted > 0 or cur.rowcount > 0


def get_queue_rollup() -> list[dict]:
    """Compound-level rollup of the open queue: one row per compound with its
    open flag count and worst breach, plus its flagged readings nested (sorted
    widest-breach first). Compounds ordered by flag count, then worst breach."""
    sql = """
        SELECT compound_id,
               count(*) AS open_flags,
               max(abs(margin)) AS worst_breach,
               json_agg(json_build_object(
                   'reading_id', reading_id, 'assay_name', assay_name,
                   'result_value', result_value, 'result_unit', result_unit,
                   'concern_direction', concern_direction, 'threshold', threshold,
                   'threshold_unit', threshold_unit, 'margin', margin,
                   'compound_prior_n', compound_prior_n,
                   'compound_prior_mean', compound_prior_mean, 'reason', reason
                 ) ORDER BY abs(margin) DESC) AS readings
        FROM review_queue
        WHERE status = 'open'
        GROUP BY compound_id
        ORDER BY open_flags DESC, worst_breach DESC
    """
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]


def get_flags_by_assay(days: int = 30) -> list[dict]:
    """Open-flag counts per assay type in the last N days — surfaces a
    miscalibrated threshold that would otherwise hide in the flat list."""
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """SELECT assay_name, count(*) AS open_flags
                 FROM review_queue
                WHERE status = 'open' AND flagged_ts >= now() - make_interval(days => %s)
                GROUP BY assay_name
                ORDER BY open_flags DESC""",
            (days,),
        )
        return [dict(r) for r in cur.fetchall()]


def get_kpi() -> dict:
    """Median (and count) time from flag-created to resolved, from real
    resolved_items rows. Not modeled."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT count(*),
                      percentile_cont(0.5) WITHIN GROUP (
                          ORDER BY EXTRACT(EPOCH FROM (resolved_ts - flagged_ts)))
                 FROM resolved_items
                WHERE flagged_ts IS NOT NULL"""
        )
        n, median_s = cur.fetchone()
        return {"resolved_count": n,
                "median_seconds": float(median_s) if median_s is not None else None}


def reopen_item(reading_id: str) -> bool:
    """Reopen a resolved item (undo)."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE review_queue
                 SET status = 'open', resolved_by = NULL, resolved_ts = NULL,
                     resolution_note = NULL
               WHERE reading_id = %s AND status = 'resolved'""",
            (reading_id,),
        )
        conn.commit()
        return cur.rowcount > 0


def upsert_flags(rows: list[dict]) -> int:
    """Upsert flagged readings into the queue, preserving reviewer status.

    On conflict the reasoning fields are refreshed but status / resolved_* are
    left untouched so a reviewer's action survives re-syncs.
    """
    if not rows:
        return 0
    cols = ["reading_id", "compound_id", "assay_name", "result_value", "result_unit",
            "concern_direction", "threshold", "threshold_unit", "margin",
            "compound_prior_n", "compound_prior_mean", "reason", "flagged_ts"]
    values = [[r.get(c) for c in cols] for r in rows]
    sql = f"""
        INSERT INTO review_queue ({", ".join(cols)}, synced_ts)
        VALUES %s
        ON CONFLICT (reading_id) DO UPDATE SET
            compound_id = EXCLUDED.compound_id,
            assay_name = EXCLUDED.assay_name,
            result_value = EXCLUDED.result_value,
            result_unit = EXCLUDED.result_unit,
            concern_direction = EXCLUDED.concern_direction,
            threshold = EXCLUDED.threshold,
            threshold_unit = EXCLUDED.threshold_unit,
            margin = EXCLUDED.margin,
            compound_prior_n = EXCLUDED.compound_prior_n,
            compound_prior_mean = EXCLUDED.compound_prior_mean,
            reason = EXCLUDED.reason,
            flagged_ts = EXCLUDED.flagged_ts,
            synced_ts = now()
    """
    template = "(" + ", ".join(["%s"] * len(cols)) + ", now())"
    with get_connection() as conn, conn.cursor() as cur:
        execute_values(cur, sql, values, template=template)
        conn.commit()
        return len(values)


def clear_stale(current_reading_ids: list[str]) -> int:
    """Mark open items 'cleared' if they are no longer flagged upstream."""
    with get_connection() as conn, conn.cursor() as cur:
        if current_reading_ids:
            cur.execute(
                """UPDATE review_queue SET status = 'cleared', synced_ts = now()
                     WHERE status = 'open' AND NOT (reading_id = ANY(%s))""",
                (current_reading_ids,),
            )
        else:
            cur.execute(
                "UPDATE review_queue SET status = 'cleared', synced_ts = now() WHERE status = 'open'"
            )
        conn.commit()
        return cur.rowcount
