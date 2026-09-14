# Prompt 03 — Genie space

> Before anything else, read `../context/00-shared-context.md` in full — it holds the constraints this prompt assumes (the architectural boundary, audit fields, tech stack). If this prompt touches the sync API surface, also read `../context/08-api-contract.md`.


Depends on prompt 01. Run this as the matching Omnigent agent from
`../agents/`, in the same project.

---

Set up a Genie space over the curated silver tables from prompt 01,
configured as code (via the Databricks CLI/API or asset bundle
config) rather than manual workspace setup, so it's reproducible.

Build:
- Genie space definition scoped to the compound registry, assay
  results, and toxicology reference silver tables — not the bronze
  layer, and not any table outside this schema.
- A set of sample natural-language questions and their expected
  intent, used as a lightweight regression check (e.g. "what were the
  last three readings for compound X" → should resolve to a filtered
  query against assay results, not a full scan). This doesn't need to
  be a formal eval suite yet — a short markdown file listing
  question/expected-behavior pairs is enough to catch obvious
  regressions later.
- Confirm (and document in a comment or README) what identity the
  Genie space runs as when called by the agent — it should be a
  scoped service principal per the shared context (`../context/00-shared-context.md`)'s grants, not an individual
  user's credentials.
- A short note on what's out of scope for this Genie space
  deliberately — e.g. it should not be able to answer questions that
  require joining against PII or any table not explicitly listed
  above, even if such a table exists elsewhere in the workspace.

Don't wire this into the agent yet — that's prompt 05.
