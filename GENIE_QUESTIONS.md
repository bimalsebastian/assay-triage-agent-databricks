# Genie sample questions — Lead-Opt Assay Triage space

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
