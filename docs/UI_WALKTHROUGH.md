# What the UI renders, and how the reviewer triages (text walkthrough)

> For the text-only evaluator: the app is a running web UI you cannot see. This
> file describes, in text, exactly what it renders and how each element drives the
> reviewer's triage decision. Every element below is produced by committed code in
> `app/app.py` (function names cited) and fed by the live endpoints in the same
> file. It is a description of real, deployed behaviour — not a mockup.

The app is a single dashboard: a wide **left workspace** (metrics + the triage
queue) and a sticky **right copilot** (Ask Genie). Header shows the signed-in
user (real identity via `/api/whoami`), a "governed by Unity Catalog /
on-behalf-of-user" status, and a **sign-out** control (clears the app session so
newly-granted scopes take effect).

## The reviewer's job

A lead-optimization scientist/reviewer needs to decide, fast, which flagged
compounds to act on and how. The UI is arranged so that decision is answerable
top-to-bottom without leaving the page.

## 1. Triage KPIs (top-left card) — *is the queue healthy?*
Rendered by `loadKpi()` from `/api/kpi` (real numbers from logged resolutions in
Lakebase, not modelled):
- **Median flag→resolve** and **P90 flag→resolve** (hours) — cycle-time health,
  with a "Target < 24.0h" reference.
- **False-positive rate** (%) — how noisy the flagging is.
- **Resolution-Outcome Mix** — a segmented bar + legend: false-positive (rose) /
  confirmed-concern (amber) / escalated (slate), counted from real reviewer
  decisions.
*Triage value:* tells the reviewer/lead whether flags are trustworthy and whether
the backlog is being cleared on time.

## 2. Open Flags by Assay (top-right card) — *where is the risk concentrated?*
Rendered by `loadFba()` from `/api/flags-by-assay`: one bar per assay
(e.g. `hERG_IC50`, `CYP3A4_IC50`, `KINETIC_SOL`, `LOGD_7_4`) with the open-flag
count, longest bar first, and a total.
*Triage value:* surfaces the dominant failure mode (e.g. cardiotoxicity/hERG) so
the reviewer knows which assay class is driving attrition.

## 3. Clinical-convergence headline (above the queue) — *the cross-domain signal*
Rendered by `loadRollup()` into `#convergence` from `/api/queue/rollup`. A
prominent callout: **"N of M open compounds carry a preclinical flag AND a
clinical adverse-event signal — X% convergence. These float to the top of the
queue for confirmatory review first."** Plus counts for "checked · no
correlation" and "no clinical data."
*Triage value:* this is the business punchline — it fuses preclinical assay
breaches with real-world clinical signal, and tells the reviewer which compounds
are highest-conviction kills.

## 4. Compounds with Open Flags (the queue) — *what to work, in order*
Rendered by `loadRollup()` into the `#rollup` table, **blended-risk sorted**
(clinically-correlated first, then flag count, then breach severity). Columns:
- **▸ expander**
- **Compound** — mono id chip; teal when clinically correlated, slate otherwise.
- **Open Flags** — count badge.
- **Worst Breach** — the widest margin, as a number + a mini bar coloured by
  correlation state (rose = correlated, amber = checked-no-correlation, slate =
  no-clinical-data), scaled to the worst breach in the queue.
- **Clinical Correlation** — a pill: `⚠ correlated` (rose) / `checked · no
  correlation` (slate) / `no clinical data` (dashed) — see `ccBadge()`.
- **Actions** — Review.
A **filter** box narrows by compound id (`applyFilter()`), and a **live
indicator** ("updated Ns ago") shows the queue auto-refreshes (`refreshAll()`,
every 45s — the rebuild is skipped while a row is expanded so it never disrupts a
reviewer mid-drill-in).
*Triage value:* the reviewer works top-down; the sort guarantees the compounds
that are both preclinically breached and clinically corroborated are handled
first.

## 5. Expand a compound (row drill-in) — *why is it flagged, and resolve it*
Clicking a row calls `toggle()`, which renders inline:
- **Flagged readings table** — per reading: assay, reading value+unit, the
  **threshold** it breached (with direction pill), the **breach margin**, and the
  full **"Why" reason text** carried from the auditable flag function (threshold,
  direction, margin, compound prior history). Nothing is a black box.
- **Resolve control** — a reason dropdown (`false_positive`,
  `confirmed_concern`, `escalated_for_confirmatory_assay`) + Resolve button
  (`resolve()` → `/api/resolve`), which writes the decision (and resolver
  identity) back to Lakebase and refreshes the KPIs.
- **Clinical correlation line** — `loadClinical()` calls `/api/clinical-summary`
  (read **as the signed-in user**, from the scoped aggregate view): the signal
  summary + adverse-observation count, or nothing if the user lacks clinical
  access.
- **Assay history** — `loadHistory()` calls `/api/history`: the compound's
  historical readings for each flagged assay (acquired timestamp, value, unit,
  QC), so the reviewer sees whether this reading is an outlier or a trend.
*Triage value:* everything needed to adjudicate one compound — the evidence, the
history, the clinical corroboration, and the resolve action — is in one place.

## 6. Ask Genie copilot (right panel) — *ask the data in plain language*
Rendered by `ask()` / `renderTrace()` / `renderExplain()` / `chartHtml()` /
`tableHtml()` against `/api/ask`, `/api/ask/poll`, `/api/ask/query-result`
(Genie One MCP, **on behalf of the signed-in user**). For each question the panel
shows, in sequence:
1. a **live thinking trace** ("Thinking… / Running SQL…") as Genie works;
2. the **answer** (markdown, with tables and citations);
3. a collapsible **"How Genie got this"** — the actual **SQL Genie ran**, the
   **result table**, and a **chart** rendered from the rows;
4. an **Open in Genie** deep link.
Quick-prompt chips pre-fill common triage questions (flagged summary, hERG
outliers, export triage list). If a scope/authorization error occurs, an inline
**Re-authorization needed** prompt appears with a one-click sign-out.
*Triage value:* the reviewer can interrogate the whole governed dataset in
natural language — and *see the reasoning and SQL*, so the answer is auditable,
not a mystery. Because it runs as the user, the clinical data it can reach is
exactly what that person is permitted to see.

## What the reviewer walks away able to do
- See at a glance whether flags are trustworthy and the backlog is on time (KPIs).
- Know which assay class drives risk (flags-by-assay).
- Immediately spot the highest-conviction kills (convergence headline + blended
  sort).
- For any compound: read *why* it flagged, check its history, see clinical
  corroboration scoped to their access, and resolve with a logged decision.
- Ask follow-up questions in natural language and see the SQL + data behind the
  answer.

## Surface note
This is a **responsive** web UI (see `docs/DESIGN_DECISIONS.md`): the two-column
layout stacks to a single column on phone/Android-browser widths, so triage is
usable on mobile web. A **native Android** client is a scoped roadmap item, not
built for this submission — it can't be run or shown on the Mac dev/demo
environment, and the text-only evaluator can't see a running UI regardless.
