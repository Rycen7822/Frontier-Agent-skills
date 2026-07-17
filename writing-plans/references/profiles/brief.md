---
{
  "card_id": "wp.profiles.brief",
  "card_version": 2,
  "kind": "procedure",
  "decision_id": "wp.select.profiles.brief",
  "required_artifact_ids": [],
  "produced_artifact_ids": ["plan-brief"],
  "max_bytes": 4096
}
---
# Brief Plan

## Decision this card owns
Produce the smallest implementation-ready plan for one bounded outcome in the current context.

## Use when
- Planning was explicitly requested and the change does not require a durable cross-context state or multi-stage rollout.

## Do not use when
- The work needs a durable handoff, program frontier, or migration map.

## Required inputs
- Intended outcome, bounded scope, current evidence, acceptance proof, and authority limits.

## Procedure
1. State one observable outcome and the smallest owned change boundary.
2. Record invariants/non-goals, the smallest coherent approach, and only evidence-backed files/symbols.
3. Record the focused before/after distinction, proportional affected gate, and false-green risk.
4. Preserve only material risks/open facts as blockers instead of inventing implementation detail.
5. Render the bounded [Brief template](../../templates/brief-change-card.md), create no workflow state, and return the typed result to Router.

## Output contract
- One `plan-brief` with outcome, scope/owner seam, invariants/non-goals, approach, proof/false-green, risks/open facts, and blockers.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop when the Brief is executable without rediscovery; do not create workflow state or publication authority.
