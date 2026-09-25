# How this solution was built (Claude Code session + prompts)

> For the text-only evaluator: this documents *how* the build was produced — the
> AI-assisted process, the exact prompts, and the discipline that guarantees the
> committed evidence is real. Nothing here is a screenshot; every artefact it
> references is text in this repo.

## Tooling

Built with **Claude Code** (Anthropic's CLI coding agent) driving the Databricks
CLI, SQL, and Python against a live Azure Databricks workspace
(`adb-7405610110498224`). The optional **conversation ID** for the build session
is available on request via the FE Bar submission form's conversation-ID field
(the form has a per-tool help link for locating it); it is intentionally not
committed to the repo.

## Method: one prompt per stage, persistent contract, evidence-gated

The build was not one monolithic prompt. It is a sequence of stage prompts, each
fed to Claude Code in order, with a persistent context file (`CLAUDE.md`) that
Claude re-reads every session. The core rule in `CLAUDE.md` is the thing that
makes this submission trustworthy:

> *"Every stage must produce real execution evidence — actual query output, actual
> run logs, actual records — committed to the repo as text, not just working
> code. A stage isn't done until you've committed that evidence."*

So each stage lands **two** things in git: the code, and the committed text
output proving it ran (`evidence/stageNN-*.txt`). Source code alone was never
accepted as "done."

## The prompt sequence (`prompts/`)

Core build — each maps to exactly one required component:

| Prompt | Stage | Component | Evidence |
|--------|-------|-----------|----------|
| `00-mock-lims-lakeflow-prompt.md` | 00 | Lakeflow — mock LIMS + custom connector → bronze | `evidence/stage00-bronze-evidence.txt` |
| `01-unity-catalog-governance-prompt.md` | 01 | Unity Catalog — governed silver + least-priv grants | `evidence/stage01-silver-evidence.txt` |
| `02-genai-intelligence-prompt.md` | 02 | ML/GenAI — auditable tox-flag UC function | `evidence/stage02-flags-evidence.txt` |
| `03-lakebase-serving-prompt.md` | 03 | Lakebase — operational review queue | `evidence/stage03-review-queue-evidence.txt` |
| `04-genie-room-prompt.md` | 04 | Genie — NL querying over silver | `evidence/stage04-genie-evidence.txt` |
| `05-databricks-app-prompt.md` | 05 | Databricks App — review dashboard | `evidence/stage05-app-evidence.txt` |
| `06-review-queue-enhancements-prompt.md` | 06 | Queue rollup / severity / KPIs | `evidence/stage06-enhancements-evidence.txt` |

Clinical / openEHR extension (converges with the base build at the crosswalk):

| Prompt | Stage | Component | Evidence |
|--------|-------|-----------|----------|
| `07-mock-ehr-aql-connector-prompt.md` | 07 | Mock openEHR CDR + AQL connector → clinical bronze | `evidence/stage07-clinical-bronze-evidence.txt` |
| `08-clinical-uc-governance-prompt.md` | 08 | Clinical UC governance (deliberately tighter grants) | `evidence/stage08-clinical-governance-evidence.txt` |
| `09-compound-drug-crosswalk-prompt.md` | 09 | Compound→drug crosswalk (cross-catalog) | `evidence/stage09-crosswalk-evidence.txt` |
| `10-extended-flagging-prompt.md` | 10 | 3-state clinical-correlation flagging | `evidence/stage10-clinical-flagging-evidence.txt` |
| `11-extended-lakebase-queue-prompt.md` | 11 | `clinical_correlation` field on the queue | `evidence/stage11-clinical-queue-evidence.txt` |
| `12-scoped-genie-clinical-prompt.md` | 12 | Scoped, aggregate-only clinical Genie space | `evidence/stage12-clinical-genie-evidence.txt` |
| `13-app-correlation-indicator-prompt.md` | 13 | Correlation indicator in the app | `evidence/stage13-app-correlation-evidence.txt` |

Later enhancement sessions (also Claude Code) then layered on: Genie One managed
MCP (stage 14, `evidence/stage14-genie-mcp-unified-evidence.txt`), the triage KPI
panel (stage 15), the convergence + blended-risk sort (stage 16), and the
Genie One MCP native render (stage 17, `evidence/stage17-genie-one-mcp-evidence.txt`).

## Build order / dependencies

`00 → 01 → 02` are strictly sequential. `03` and `04` both depend on `01`+`02`
but not on each other. `05` needs both `03` and `04`. In the clinical track, `07`
is independent until `09` (the convergence point); everything from `09` on is
sequential. See `README.md` for the full graph.

## How to re-run / reproduce

- To rebuild the *logic*: feed `prompts/00…13` to Claude Code in the root of this
  repo (it auto-reads `CLAUDE.md`).
- To stand up the *infrastructure* from scratch in a fresh workspace: follow
  `DEPLOY.md` (resource-by-resource runbook + inventory).
- To confirm it *ran*: read the `evidence/*.txt` files — they contain real query
  output, run logs, and records (240 ingested rows, 14 flagged, live queue,
  logged reviewer resolutions), not descriptions of them.
