# Prompt 00 — mock LIMS + custom Lakeflow connector

> Read `../CLAUDE.md` in full first — it has the workspace, catalog,
> and problem framing this prompt assumes.

---

Build the raw-data entry point for this system: a mock LIMS service
and a custom Lakeflow connector that ingests from it.

Build:

- A small REST API (FastAPI is fine) simulating a LIMS assay-results
  export endpoint. Make the payload shape deliberately realistic and
  a little awkward, the way a real LIMS export often is — nested
  under a vendor-specific key, timestamps in a non-ISO format, sample
  IDs that need a regex split to get compound ID out. Don't make this
  clean JSON; the point of a custom connector is handling a format a
  managed connector wouldn't.
- Synthetic data generation feeding that API: a batch of assay
  readings across a handful of synthetic compound IDs, with enough
  variation that some readings will later trip a toxicity threshold
  and most won't. Keep it clearly synthetic — no real compound names,
  no real company references anywhere in the data or the code.
- A custom Lakeflow connector implementing Databricks' `LakeflowConnect`
  interface (see the `databrickslabs/lakeflow-community-connectors`
  repo for the interface and, if this workspace has it enabled, the
  Claude Code skills that scaffold this) with `__init__` (auth to the
  mock API), `list_tables` (the endpoints it exposes), and
  schema-discovery/read methods that unmarshal the awkward payload
  into a clean, defined schema.
- A Lakeflow Declarative Pipeline (or job) running that connector and
  landing the result in `lead_opt_demo.bronze.assay_results_raw` (or
  equivalent — confirm the catalog exists per CLAUDE.md first, create
  it if not).
- Confirm this actually ran: after the pipeline runs, run a `SELECT`
  against the bronze table and commit the real result (row count,
  a handful of sample rows) as text in the repo — this is your first
  piece of execution evidence, and everything downstream depends on
  this table actually having data in it.

Don't build the silver/governance layer yet — that's the next prompt,
and it reads from what this one produces.
