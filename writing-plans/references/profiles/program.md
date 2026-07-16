---
{
  "card_id": "wp.profiles.program",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "plan_route",
    "request_source",
    "scope_projection",
    "authority_projection",
    "dependency_evidence"
  ],
  "produces": [
    "program_plan",
    "program_frontier"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Program Plan

## Decision this card owns
Define a durable multi-stage plan and its current executable frontier without turning the model context into the state store.

## Use when
- The work spans stages, migrations, rollback boundaries, resumable execution, or public contract changes.

## Do not use when
- A bounded Brief or single handoff is sufficient, or Closure Contract compilation is required first.

## Required inputs
- Intended outcomes, source/scope/authority identities, dependency evidence, rollout and rollback constraints, and required proof.

## Procedure
1. Define coarse milestones and typed outcome nodes/edges while keeping future fog deliberately coarse.
2. Record major decisions, constraint coverage, invalidated/superseded lineage, blockers, and compatibility/expand-migrate-contract order.
3. Identify the detailed current topologically ready conflict-safe frontier and next slices.
4. Bind rollout, approval, resource/retry/idempotency, verification, risk, and rollback obligations to their owners.
5. Persist canonical state/full graph/evidence/alternatives outside the card and render only the bounded [Program template](../../templates/program-migration-map.md) current-frontier view.
6. For closure, bind contract ID/hash/epoch/coverage without copying statements or actual SQW execution state.

## Output contract
- `program_plan` identity/state lineage plus ≤8,192-byte reconstructable `program_frontier` with constraints, decisions, next slices, risk/rollback, evidence gates, and blockers.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop after the current frontier is executable or a typed blocker identifies the next planning decision.
