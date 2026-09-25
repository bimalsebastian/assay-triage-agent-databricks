# DEPLOY.md — stand up the Lead-Opt Assay Triage build from scratch

`README.md` covers *building* the solution (feeding the `prompts/` to Claude Code
against a live workspace). This file is the operator's runbook: the concrete
resources the build creates and the order to provision them in a **fresh**
workspace, so the whole end-to-end journey is reproducible, not just readable.

The reference deployment runs on Azure Databricks workspace
`adb-7405610110498224`, catalogs `lead_opt_demo` (+ `lead_opt_demo_clinical`).
Swap those names for your own; nothing below hardcodes them except where noted.

---

## 0. Prerequisites

- Databricks CLI (`databricks -v` ≥ 0.220) authenticated to the target workspace:
  ```bash
  databricks auth login --host https://<your-workspace>.azuredatabricks.net --profile lead-opt
  export DATABRICKS_CONFIG_PROFILE=lead-opt
  databricks current-user me        # must succeed before anything else
  ```
- Workspace entitlements: **Unity Catalog**, **Lakeflow Declarative Pipelines**
  (serverless), **Lakebase** (managed Postgres), **Databricks Apps**, **Genie**,
  and a **serverless SQL warehouse**.
- Python 3.10+ locally (for the Lakebase DDL/sync helpers and Genie space builders).

Provision in this order — each stage consumes the previous stage's output.

---

## 1. Unity Catalog — catalogs, schemas, grants (prompt 01 / 08)

```bash
databricks catalogs create lead_opt_demo
databricks schemas create bronze lead_opt_demo
databricks schemas create silver lead_opt_demo
# clinical extension (optional, prompts 07-13) — deliberately separate catalog:
databricks catalogs create lead_opt_demo_clinical
databricks schemas create bronze lead_opt_demo_clinical
databricks schemas create silver lead_opt_demo_clinical
```

Least-privilege grants are applied by the transforms (`transforms/01_silver.sql`,
`transforms/08_clinical_silver.sql`) — `GRANT SELECT` to the app service
principal only, and the clinical catalog is granted **more tightly** than the
preclinical one (see `GOVERNANCE_NOTES.md`). Grant `USE CATALOG`/`USE SCHEMA` to
the human reviewers who will sign in to the app (their identity is what Unity
Catalog enforces at query time — see the OBO section below).

## 2. Secret scope for the mock source systems

The mock LIMS/EHR services are protected by bearer tokens the connectors read at
ingestion time (`SECRET_SCOPE = "lead_opt"` in `pipelines/ingest_*.py`):

```bash
databricks secrets create-scope lead_opt
databricks secrets put-secret lead_opt mock_lims_bearer   # U2M token, see note
databricks secrets put-secret lead_opt mock_ehr_bearer    # clinical extension only
```

> These are U2M OAuth tokens and **expire ~1h** — refresh them before re-running
> ingestion. (A production connector would use a service-principal M2M token.)

## 3. Mock source systems (Databricks Apps) (prompt 00 / 07)

The raw data enters from LIMS-flavoured (not clean-JSON) mock services, so the
connector does real parsing — nothing upstream is hand-seeded.

```bash
# Mock LIMS
databricks sync mock_lims /Workspace/Users/<you>/lead-opt/mock-lims
databricks apps create lead-opt-mock-lims
databricks apps deploy lead-opt-mock-lims --source-code-path /Workspace/Users/<you>/lead-opt/mock-lims
# Mock openEHR CDR (clinical extension)
databricks sync clinical/mock_ehr /Workspace/Users/<you>/lead-opt/mock-ehr
databricks apps create lead-opt-mock-ehr
databricks apps deploy lead-opt-mock-ehr --source-code-path /Workspace/Users/<you>/lead-opt/mock-ehr
```

Put each app's URL + the bearer it expects into config: the pipelines read
`mock_lims.host` / `mock_ehr.host` from `databricks.yml` (`configuration:` block)
and the bearer from the secret scope above.

## 4. Lakeflow ingestion → bronze (prompt 00 / 07)

The custom connectors (`connectors/mock_lims/connector.py`,
`connectors/mock_ehr/connector.py`) land raw records in Delta bronze via the
Declarative Pipelines defined in `databricks.yml`:

```bash
# edit databricks.yml: set mock_lims.host / mock_ehr.host to your app URLs
databricks bundle deploy -t demo
databricks bundle run ingest_bronze -t demo
databricks bundle run ingest_clinical_bronze -t demo   # clinical extension
```

Verify against the committed evidence shape: `evidence/stage00-bronze-evidence.txt`
(240 rows, 24 compounds, 5 assays).

## 5. Silver + intelligence + crosswalk (SQL, prompts 01/02/08/09/10)

Run the transforms in order on a serverless SQL warehouse (note its **warehouse
id** — you'll need it for the app):

```bash
W=<your-warehouse-id>
for f in transforms/01_silver.sql transforms/02_flagging.sql \
         transforms/08_clinical_silver.sql transforms/09_crosswalk.sql \
         transforms/10_clinical_flagging.sql transforms/12_clinical_summary_view.sql; do
  databricks sql-statements execute --warehouse-id "$W" --statement "$(cat $f)"
done
```

`02_flagging.sql` creates the **auditable** `check_toxicity_flag(...)` UC function
(deterministic threshold rule + full reasoning, *not* an LLM black box) and the
`assay_flags` batch table. Expected: 14 flagged of 240
(`evidence/stage02-flags-evidence.txt`).

## 6. Lakebase — operational review queue (prompt 03 / 11)

Create the Lakebase (Postgres) project and load the schema; populate it *from*
governed silver + flags (never from raw data — Delta stays the system of record):

```bash
# Create a Lakebase database project named e.g. lead-opt-triage (db: lead_opt)
# via the workspace UI or `databricks database` commands, then note its host.
LAKEBASE_HOST=<ep-xxxx.database.<region>.azuredatabricks.net>

# Load schema (schema.sql base; schema_v2/v3 add the clinical + resolution columns):
psql "host=$LAKEBASE_HOST dbname=lead_opt sslmode=require ..." -f serving/schema.sql
psql ... -f serving/schema_v2.sql
psql ... -f serving/schema_v3.sql

# Sync flags -> queue (run as the app SP; reads silver, writes review_queue):
python serving/sync_review_queue.py
```

Evidence shape: `evidence/stage03-review-queue-evidence.txt` (14 open items).

## 7. Genie spaces (prompt 04 / 12)

Build the preclinical (open) space over the silver tables and the **scoped,
aggregate-only** clinical space (never expose patient-level detail through the
open NL surface):

```bash
python genie/build_space_payload.py            # preclinical space over silver
python genie/build_clinical_space_payload.py   # scoped clinical (aggregate) space
```

Grant the human reviewers `CAN_RUN` on both spaces. Governance is enforced by
Unity Catalog on the **caller's** identity (OBO), not the space config.

> Genie access from the app goes through the **Genie One managed MCP** endpoint
> (`/api/2.0/mcp/genie`) — one auto-routed NL surface, no room dropdown. See
> `genie/genie_mcp.py`.

## 8. Review dashboard (Databricks App) (prompt 05 / 13)

```bash
databricks sync app/ /Workspace/Users/<you>/lead-opt/review-app
databricks apps create lead-opt-review
# HYBRID identity: user OBO for Genie + governed reads; app SP for the queue.
databricks apps update lead-opt-review --json '{"user_api_scopes":["sql","genie"]}'
databricks apps deploy lead-opt-review --source-code-path /Workspace/Users/<you>/lead-opt/review-app
```

Set the app's environment (`app/app.yaml` + Apps runtime injects
`DATABRICKS_CLIENT_ID/SECRET`):

| Env | Value |
|-----|-------|
| `LAKEBASE_HOST` | your Lakebase endpoint host |
| `PGDATABASE` | `lead_opt` |
| `WAREHOUSE_ID` | your serverless warehouse id |

Grant the app SP: `SELECT` on `lead_opt_demo.silver.*`, `CAN_USE` on the
warehouse, `CAN_RUN` on the Genie spaces, and a Lakebase role that can
read/write `review_queue` + `resolved_items`.

> **Deploy gotcha:** `app/lakebase.py` and `app/genie_mcp.py` are gitignored
> copies of `serving/lakebase.py` and `genie/genie_mcp.py`. `databricks sync`
> honours `.gitignore` and skips them, so on a *first* deploy import them
> explicitly (`databricks workspace import ...`) before `apps deploy`. Also
> `app/app.py`'s `INDEX_HTML` must stay a raw string (`r"""..."""`).

---

## 9. First-run verification

Open the app URL. On first load you'll be prompted to **consent** to the `sql`
and `genie` user scopes (OBO). Then:

- The KPI panel shows real numbers from logged resolutions in Lakebase.
- The queue lists the flagged compounds, blended-risk sorted.
- Ask Genie answers **as you** (UC scopes the result to your grants); the panel
  shows Genie's thinking trace, the SQL it ran, and a chart from the rows.

### Re-authorization gotcha
Databricks Apps keep their **own** encrypted session cookie (24h TTL),
independent of the workspace session. If you change `user_api_scopes` after a
user has already signed in, that browser keeps a stale token and Genie fails with
`403 Invalid scope, required scopes: genie`. Fix: the app's header **sign-out**
button (or navigate to `https://<app-host>/.auth/sign_out`) clears the cookie and
forces fresh consent with the new scopes. An incognito window also works.

---

## Resource inventory (what a full deployment creates)

| Layer | Resource |
|-------|----------|
| Unity Catalog | catalogs `lead_opt_demo`, `lead_opt_demo_clinical` (bronze/silver schemas) |
| Secrets | scope `lead_opt` (`mock_lims_bearer`, `mock_ehr_bearer`) |
| Apps (sources) | `lead-opt-mock-lims`, `lead-opt-mock-ehr` |
| Lakeflow | pipelines `ingest_bronze`, `ingest_clinical_bronze` (serverless) |
| Lakebase | project `lead-opt-triage`, db `lead_opt` (`review_queue`, `resolved_items`) |
| SQL warehouse | one serverless warehouse (for transforms + app governed reads) |
| Genie | preclinical space (over silver) + scoped clinical space (aggregate-only) |
| Apps (UI) | `lead-opt-review` (hybrid OBO: `sql`,`genie` user scopes) |

All data is **synthetic** — generated by the mock LIMS/EHR services. No real
compounds, patients, or customer identifiers.
