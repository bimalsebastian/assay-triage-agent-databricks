# Prompt 01 — Unity Catalog governance

> Read `../CLAUDE.md` in full first. Depends on prompt 00 — this
> reads from the bronze table it produced.

---

Turn the raw bronze data from prompt 00 into governed, curated silver
tables.

Build:

- A transform (SQL or a Lakeflow Declarative Pipeline stage) reading
  from `lead_opt_demo.bronze.assay_results_raw` and writing curated
  silver tables: `assay_results` (cleaned, typed, one row per
  reading), `compound_registry` (distinct compounds seen, with a
  placeholder structure identifier), and a `tox_reference` table with
  synthetic reference thresholds per compound family — generate this
  reference data yourself if prompt 00 didn't already include it,
  clearly marked as synthetic.
- Unity Catalog grants: read access for whatever principal the Genie
  space and the flagging function will run as (prompt 02/04), write
  access scoped narrowly to this pipeline — not broad catalog-wide
  write access for anything else.
- A data-quality check on the silver tables — reject or quarantine
  rows with a null compound ID or an out-of-range reading rather than
  silently loading bad data.
- Confirm this ran for real: run the transform, then run a `SELECT
  COUNT(*)` and a small sample query against each silver table, and
  commit that actual output as text in the repo.

Don't build the flagging logic yet — that's the next prompt, and it
reads from `assay_results` and `tox_reference` here.
