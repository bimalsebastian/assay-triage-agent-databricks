# Databricks-side build — Omnigent agent package

This is the same seven-stage Databricks-side build as the plain
Claude Code version, repackaged to run through Omnigent
(`docs.databricks.com/.../omnigent/`) instead of pasting prompts
directly into a chat session.

## What changed from the plain-prompt version, and why

Omnigent doesn't auto-load a `CLAUDE.md` the way a Claude Code session
does, so the shared project context is now its own file
(`context/00-shared-context.md`) that every stage prompt references
explicitly, and each stage is wrapped in a small `.agent.yaml` that
pins the harness/model and adds a couple of governance policies —
this is Omnigent's actual value-add over a plain prompt: stateful
control at the orchestration layer instead of only in the system
prompt.

## Layout

```
context/     shared project context + the API contract (unchanged content)
prompts/     the seven stage prompts (same content as before, now pointing at context/)
agents/      one .agent.yaml per stage — what you actually run
policies/    design note + stub for the one policy worth adding deliberately
```

## Before you start

1. Confirm the **Omnigent** preview is enabled for your workspace
   (workspace admin, under Previews) — it's currently a Beta feature.
2. Install Omnigent locally if you're not running purely against the
   managed Databricks server (see Omnigent's own quick start for the
   install command).
3. In every `agents/*.agent.yaml`, replace the `auth.profile` value
   (`oss` is a placeholder from Omnigent's docs) with whatever profile
   your workspace is actually configured under.
4. Bring `08-api-contract.md` into `context/` from the Android
   builder's copy (or vice versa) so both sides stay byte-identical —
   same rule as the plain Claude Code version.

## Running it

Each stage is one command, run in order from this folder:

```
omnigent run agents/01-lakehouse-schema.agent.yaml
omnigent run agents/02-uc-functions.agent.yaml
omnigent run agents/03-genie-space.agent.yaml
omnigent run agents/04-lakebase-session-store.agent.yaml
omnigent run agents/05-agent-bricks-orchestrator.agent.yaml
omnigent run agents/06-sync-api.agent.yaml
omnigent run agents/07-databricks-app-web.agent.yaml
```

01–04 have no dependency on each other and can be run in parallel
sessions (Omnigent's collaboration model supports this — separate
live sessions, shareable by URL if someone else needs to watch one
run). 05 onward is sequential.

## The one policy worth using deliberately

`policies/promotion-approval-gate.md` explains why: the build's own
rule is that Delta promotion only happens after human approval, and
Omnigent's policy engine can enforce that at the runtime layer instead
of only by convention in a prompt. It's commented out in agents 05
and 06 by default because the exact enforcement-point syntax needs to
be confirmed against your installed Omnigent version first — read
that file before enabling it. Everything else in this package (the
`cost_budget` policy on every agent) uses a confirmed, documented
built-in and needs no changes to work as written.

## What this package deliberately doesn't do

It doesn't turn the whole seven-stage build into one multi-agent
Omnigent session with sub-agents and handoffs (the pattern Omnigent's
own examples call "Cross-Harness Coding" or "Harness Portability").
That's a legitimate next step if you want a stronger Omnigent story
for the deck, but it adds real complexity for a 4-8 hour build — seven
separate single-agent runs, executed in dependency order, is enough to
demonstrate the meta-harness genuinely doing something (governed
execution, budget policies, a shareable session) without spending your
time budget on orchestration plumbing instead of the actual six-stage
data journey the submission is graded on.
