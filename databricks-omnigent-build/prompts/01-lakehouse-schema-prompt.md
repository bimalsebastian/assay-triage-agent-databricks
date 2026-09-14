# Prompt 01 — Lakehouse Delta schema

> Before anything else, read `../context/00-shared-context.md` in full — it holds the constraints this prompt assumes (the architectural boundary, audit fields, tech stack). If this prompt touches the sync API surface, also read `../context/08-api-contract.md`.


Run this as the matching Omnigent agent from `../agents/` (see that
file's `instructions:` path), from the Databricks Asset Bundle project
root.

---

Set up the Unity Catalog structure and curated Delta tables that back
this system, per the shared context (`../context/00-shared-context.md`). Implement as SQL DDL (or a Databricks
Asset Bundle notebook/job that runs it), not manual workspace clicks,
so it's reproducible.

Build:
- A catalog/schema layout (e.g. `<env>.drug_discovery`) with separate
  bronze (raw, append-only landing) and silver (curated, governed)
  layers for: compound registry, assay results, and toxicology
  reference data. Use placeholder column sets reasonable for each
  (compound ID, structure identifier, assay type, reading value/unit,
  timestamp, source) and note clearly in comments where a real schema
  from an existing LIMS/ELN would need to replace the placeholder.
- The audit/lineage columns every promoted record needs, per
  the shared context: `device_id`, `operator_id`, `capture_ts`, `sync_ts`,
  `source_flag`. These belong on the assay results silver table
  specifically, since that's what gets written to from the approval
  flow later.
- Unity Catalog grants scaffolding (least-privilege: read for Genie
  service principal, write only for the UC function / approval
  pathway — not broad write access).
- A small number of representative seed rows for local development and
  for the later Genie space prompt to have something real to query
  against.
- A basic data-quality check (e.g. a SQL assertion or Delta constraint)
  that `sync_ts >= capture_ts` and that `source_flag` is one of the
  two allowed values — catch bad data at the boundary, not downstream.

Don't build UC functions or the Genie space yet — those are separate
prompts that read this schema.
