# Genie sample questions — Lead-Opt Assay Triage space

> **Access (stage 17):** the app now asks **Genie One** — the single workspace-wide
> managed MCP server (`{host}/api/2.0/mcp/genie`, tools `genie_ask` /
> `genie_poll_response`), wrapped by `genie/genie_mcp.py :: GenieOneMCP.ask(question)`.
> There is no space to pick and no room dropdown: Genie One routes each question to
> the right data via the workspace Genie Ontology. The spaces below still exist and
> Genie One routes to them, but the app no longer targets them individually.
>
> **Governance under Genie One:** because it is a single natural-language surface,
> the preclinical/clinical separation is enforced by **Unity Catalog on the calling
> identity**, not by a scoped room. The app calls as its service principal, which
> stage 08 UC-denied the raw clinical tables — so patient-level data is unreachable
> through this surface (verified live: the SP can answer preclinical and aggregate
> clinical-correlation questions, but a patient-level question is refused).
>
> The per-space client (`GenieMCP`, `{host}/api/2.0/mcp/genie/{space_id}`) remains in
> `genie_mcp.py` for targeting one specific room; the app just doesn't use it.


Natural-language questions a scientist would actually ask, with the table/join
each should resolve to. Doubles as a lightweight regression check and demo
script. Space is scoped to exactly `lead_opt_demo.silver.{assay_results,
compound_registry, tox_reference, assay_flags}`.

| # | Question | Should resolve to |
|---|----------|-------------------|
| 1 | Which compounds are currently flagged? | `assay_flags` WHERE `is_flagged = true` |
| 2 | What were the last three readings for CMPD00012? | `assay_results` filter `compound_id`, ORDER BY `acquired_ts` DESC LIMIT 3 |
| 3 | How does CMPD00012's hERG_IC50 reading compare to the reference threshold? | `assay_results` JOIN `tox_reference` ON `assay_name` |
| 4 | Which assay has the most flagged readings? | `assay_flags` WHERE `is_flagged`, GROUP BY `assay_name` |
| 5 | How many compounds are in the registry? | `compound_registry` COUNT |
| 6 | What are the concern thresholds for each assay? | `tox_reference` |
| 7 | List compounds with a flagged hERG_IC50 reading below 1 uM. | `assay_flags` WHERE `assay_name='hERG_IC50'` AND `is_flagged` |
| 8 | Show the average hERG_IC50 result per compound. | `assay_results` WHERE `assay_name='hERG_IC50'`, GROUP BY `compound_id` |

## Clinical correlation (stage 12) — separate scoped room "Lead-Opt Clinical Correlation"

Aggregate-only room over `lead_opt_demo.silver.clinical_correlation_summary`
(no patient-level data, no clinical catalog access).

| # | Question | Should resolve to |
|---|----------|-------------------|
| C1 | Which flagged compounds have a clinical correlation? | `clinical_correlation_summary` WHERE `correlation_state='correlated'` |
| C2 | How many compounds fall in each correlation state? | `clinical_correlation_summary` GROUP BY `correlation_state` |
| C3 | Which compounds have no clinical mapping available? | `clinical_correlation_summary` WHERE `correlation_state='no_mapping'` |
