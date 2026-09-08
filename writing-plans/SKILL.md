---
name: writing-plans
description: Plan implementation from settled decisions, including handoffs and multi-session work.
metadata:
  version: 9.0.0
---

# Writing Plans

Turn settled decisions into an executable order of work. Inspect the relevant source and existing checks so the plan names real owners, behavior and dependencies. Resolve consequential design or diagnosis gaps first; a plan should not hide them inside implementation steps.

For work that fits the current context, write a short ordered plan. State what changes, where it belongs, what must remain true and how completion will be checked. Include exact commands or edits when they are known and useful; identify unknowns instead of inventing runnable details. Share a check across coherent changes when it can establish the same result once.

Scale detail to the handoff risk. A straightforward edit needs no identity protocol, milestone template or new planning artifact. When another context must resume the work, use [durable handoffs](references/handoff.md) to preserve the decisions and next action that would otherwise be lost.

Keep the plan current as authorized work reveals new facts. Respect an explicitly frozen specification or protected owner boundary; an ordinary implementation plan does not become immutable merely because it is written down.

For a planning-only request, deliver the plan. When the user asks to plan and execute, continue implementation and verification after planning. Reuse existing authorization; completing a plan does not create another approval gate.
