# Promotion approval gate — design note

This is the one piece of "Control" (Omnigent's policy pillar) worth
using deliberately in this build, because it maps to a real
requirement rather than being added for its own sake: `CLAUDE.md`
(now `../context/00-shared-context.md`) states that
`promote_approved_record` must only ever be called after explicit
human approval in the web app — never automatically on sync. Instead
of relying on that being followed by convention in a prompt, this
policy enforces it at the orchestration layer, which is a materially
stronger guarantee and a good story for the deck ("the same approval
gate a GxP process needs was enforced by the agent runtime, not just
described in a system prompt").

## What's confirmed vs. what you need to verify

Confirmed from Omnigent's own docs: policies are declarative gates
evaluated at enforcement points (`request`, `response`, and tool-call/
tool-result related points), returning `ALLOW`, `DENY`, or `ASK`
(pauses for human approval); a `type: function` policy points at a
Python `handler`, optionally parameterized via `factory_params`; and
built-ins like `omnigent.policies.builtins.cost.cost_budget` and
`omnigent.policies.builtins.safety.ask_on_os_tools` follow this same
shape.

**Not confirmed — verify before relying on it:** the exact enforcement
point name for gating a specific tool call by name (used as `on:
[tool_call]` below), and the exact handler function signature. Check
your installed Omnigent version's `docs/POLICIES.md` for both before
running this for real. The stub below is a reasonable starting
implementation, not a guaranteed-correct one.

## Stub handler

Put this at a Python-importable path in the project (e.g.
`src/policies/gate_promotion.py`), matching whatever module path you
reference from `handler:` in the agent YAML files.

```python
"""
Gates any tool call to promote_approved_record behind confirmation
that the target record actually has a human approval recorded in
Lakebase. Verify this against your installed Omnigent version's
policy handler signature before relying on it — the shape below
(inspecting a tool-call event and returning a verdict) is inferred
from Omnigent's documented ALLOW/DENY/ASK model, not copied from a
confirmed example.
"""

from omnigent.policies import Verdict  # confirm this import path locally

GATED_TOOL_NAME = "promote_approved_record"


def gate_promotion(event, **kwargs):
    if getattr(event, "tool_name", None) != GATED_TOOL_NAME:
        return Verdict.ALLOW

    record_id = event.tool_input.get("lakebase_record_id")
    if not record_id:
        return Verdict.DENY

    # Look up the record's approval status directly — don't trust a
    # flag passed in the tool call itself, since that's exactly what
    # this gate exists to not take on faith.
    approved = lookup_approval_status(record_id)  # implement against
                                                    # the Lakebase access
                                                    # layer from prompt 04

    if approved:
        return Verdict.ALLOW
    return Verdict.ASK  # pause for a human to confirm before promoting
```

## Wiring it into agents 05 and 06

```yaml
policies:
  gate_promotion:
    type: function
    handler: policies.gate_promotion.gate_promotion
    on: [tool_call]   # confirm this enforcement-point name locally
```

If your installed Omnigent version doesn't support gating by tool
name at this enforcement point, the fallback is to keep the
convention-based approach from the original prompts (the agent's own
instructions say never to call this function without approval) and
treat this policy as a defense-in-depth addition once you've
confirmed the syntax — not a blocker to shipping the rest of the
build in your time budget.
