# Prompt 04 — Genie Room

> Read `../CLAUDE.md` in full first. Depends on prompt 01 (reads the
> silver tables) — does not depend on prompts 02 or 03, so this can
> be built in parallel with those.

---

Set up a Genie Room over the curated silver tables from prompt 01 (and
`assay_flags` from prompt 02 if it's ready — if not, scope this to
the three prompt-01 tables and revisit once flags exist).

Build:

- A Genie space configured via the Databricks CLI/API (not manual
  workspace clicks) scoped to exactly: `assay_results`,
  `compound_registry`, `tox_reference`, and `assay_flags` once
  available. Nothing outside this catalog.
- A short markdown file, `GENIE_QUESTIONS.md`, listing 6-8 sample
  natural-language questions a scientist would actually ask (e.g.
  "what were the last three readings for compound X", "which
  compounds are currently flagged", "how does this reading compare to
  the reference threshold") with a one-line note on what table/join
  each should resolve to. This is your lightweight regression check
  and also useful material for the deck's demo.
- Confirm the service principal or identity the Genie space runs as
  is scoped per the grants set up in prompt 01, not your own personal
  credentials.
- Confirm this ran for real: actually ask the Genie space each
  question from `GENIE_QUESTIONS.md` and commit the real
  question/answer pairs as text — this is your Genie execution
  evidence, and a description of what it should be able to answer is
  not a substitute for showing that it did.
