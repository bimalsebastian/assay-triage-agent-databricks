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


def resolve_item(reading_id: str, resolved_by: str, note: str | None = None) -> bool:
    """Mark a queued item resolved. Stage 05's app triggers this on reviewer action."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE review_queue
                 SET status = 'resolved', resolved_by = %s, resolved_ts = now(),
                     resolution_note = %s
               WHERE reading_id = %s AND status = 'open'""",
            (resolved_by, note, reading_id),
        )
        conn.commit()
        return cur.rowcount > 0


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
