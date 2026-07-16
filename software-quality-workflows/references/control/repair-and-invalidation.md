---
{
  "card_id": "sqw.control.repair-and-invalidation",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "typed_dependency_projection",
    "changed_refs_and_fields",
    "current_authority_and_evidence"
  ],
  "produces": [
    "repair_scope_and_invalidation_decision"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Repair and Invalidation

## Decision this card owns
Propagate changed facts through typed dependencies and decide bounded local repair versus mandatory parent/global replan.

## Use when
- New evidence, source drift, failed proof, changed assumption, side effect, or artifact revision may invalidate preserved workflow state.

## Do not use when
- No canonical dependency/state projection exists or the task is ordinary initial implementation/diagnosis.

## Required inputs
- Changed refs/fields/content hashes, typed data/evidence/invariant/effect/resource/control edges and sensitivity fields, source/scope/plan/state versions, preserved dependencies, side effects/rollback, authority/approval, locks/leases/background work, and retry budget.

## Procedure
1. Traverse outgoing typed edges from changed refs; field-sensitive edges propagate only on intersecting declared fields, while missing field detail fails conservative. Explicit edge semantics outrank inferred dependencies.
2. Return affected/invalidated/preserved IDs, rechecks, new frontier, and reasons without mutating canonical state unless a validated projection write is explicitly requested.
3. Permit local repair only at one modeled owner seam when preserved dependencies remain fresh/equivalent, effects are known/reversible, precision fixture exists, and retry/approval budget remains valid.
4. Require `global_or_parent_replan` for goal/non-goal/authority/security/approval, global invariant/root cause, multi-owner source drift, hidden/shared state, uncertain rollback, insufficient locality, unmodeled resource coupling, exhausted local budget, or canonical objective/plan-hash change.
5. Reconcile source/scope/plan/evidence hashes, state/event versions, locks/leases and background work before resume; keep drift visible.
6. Emit a bounded repair projection, plan-change proposal, or blocked state; never silently rewrite decisions, broaden scope, grant approval, or retry non-idempotent effects.

## Output contract
- Changed refs/fields; affected/invalidated/preserved IDs; propagation evidence; required rechecks/frontier; `local_repair|global_or_parent_replan|blocked`; scope/budget/authority; resume reconciliation and reasons.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at explicit repair scope or escalation; never hide changed assumptions behind a local retry.
