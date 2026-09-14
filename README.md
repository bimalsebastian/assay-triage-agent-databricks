# Pharma lead-optimization triage — Claude Code build package

Six stages, one per required component (Lakeflow, Unity Catalog,
Lakebase, ML/GenAI, Genie, Databricks App), built as an integrated
journey against your real Azure Databricks workspace.

## One-time setup

1. Install the Databricks CLI if you haven't already.
2. Authenticate against this specific workspace — don't rely on
   whatever profile happens to be default:

   ```bash
   databricks auth login \
     --host https://adb-7405610110498224.4.azuredatabricks.net \
     --profile lead-opt-demo
   ```

   This opens a browser for a one-time OAuth login, then saves the
   profile to `~/.databrickscfg`.

3. Verify it worked:

   ```bash
   databricks auth profiles
   databricks current-user me --profile lead-opt-demo
   ```

   Both should succeed and show your identity against
   `adb-7405610110498224.4.azuredatabricks.net` before you do
   anything else. If `current-user me` fails, fix that first — every
   later step assumes this works.

4. Set the profile as the default for this project so Claude Code's
   shell commands don't need `--profile` repeated everywhere:

   ```bash
   export DATABRICKS_CONFIG_PROFILE=lead-opt-demo
   ```

   Put this in your shell profile or a project-local `.env` you
   source before starting Claude Code, so it's set for the whole
   session.

5. Confirm you can actually create things in this workspace — quick
   sanity check before committing real build time:

   ```bash
   databricks catalogs list
   databricks unity-catalog schemas list <some-existing-catalog>
   ```

## Running the build

Open Claude Code in this repo's root — it auto-reads `CLAUDE.md`.
Feed the prompts in order, one per sitting:

```
prompts/00-mock-lims-lakeflow-prompt.md
prompts/01-unity-catalog-governance-prompt.md
prompts/02-genai-intelligence-prompt.md
prompts/03-lakebase-serving-prompt.md
prompts/04-genie-room-prompt.md          <- can run in parallel with 03
prompts/05-databricks-app-prompt.md
```

00 → 01 → 02 are strictly sequential. 03 and 04 both depend on 01/02
but not on each other, so you can do them in either order or
interleave them. 05 needs both 03 and 04 done.

For each stage: paste the prompt file's content into Claude Code,
let it work, review what it built, then **commit the code and the
real execution output together** before moving to the next prompt —
per `CLAUDE.md`, a stage isn't done until that evidence is committed.

## What happened to the earlier Android/Omnigent-flavored package

Superseded. That package was scoped for a different mobility
engagement and was being carried forward out of habit, not because
it belongs in this submission. This package is the one to build from
— it drops Android and the sync-API design entirely, and adds the
Lakeflow raw-ingestion stage (prompt 00) that was missing before.
