---
{
  "card_id": "wp.profiles.program",
  "card_version": 2,
  "kind": "procedure",
  "decision_id": "wp.select.profiles.program",
  "required_artifact_ids": [],
  "produced_artifact_ids": ["plan-program"],
  "max_bytes": 8192
}
---
# Program Plan

## Decision this card owns
Define a durable multi-stage plan and its current executable frontier without turning the model context into the state store.

## Use when
- The work spans stages, migrations, rollback boundaries, resumable execution, or public contract changes.

## Do not use when
- A bounded Brief or single handoff is sufficient.

## Required inputs
- Intended outcomes, source/scope/authority identities, dependency evidence, rollout and rollback constraints, and required proof.

## Procedure
1. Define coarse milestones and typed outcome nodes/edges while keeping future fog deliberately coarse.
2. Record major decisions, constraint coverage, invalidated/superseded lineage, blockers, and compatibility/expand-migrate-contract order.
3. Identify the detailed current topologically ready conflict-safe frontier and next slices.
4. Bind rollout, approval, resource/retry/idempotency, verification, risk, and rollback obligations to their owners.
5. Submit the closed Program payload to `card_cycle.py`; the caller pre-creates the external owner root, and the CLI alone initializes the locked v3 state, ordered queue, `artifacts/`, and `projections/`.
6. When a costly durable architecture choice changes a public/data/security/runtime/deployment/storage/ownership contract, decide whether an ADR is justified under the project's existing convention and documentation authority.
7. A proposed ADR records status, context, exact decision/owners/contracts, materially considered alternatives and rejection evidence, consequences, proof/rollback, and supersession lineage. Preserve historical ADRs and never infer acceptance or publication authority.

## Output contract
- One Program owner locator plus the exact next queue card or terminal status. `program.md` is a disposable fixed projection with a total ≤8,192-byte envelope; canonical truth remains only in locked state.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop after the current frontier is executable or a typed blocker identifies the next planning decision.
