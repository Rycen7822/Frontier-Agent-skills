---
{
  "card_id": "sqw.delegation.candidate-worker-contract",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "admitted_isolated_write_slice",
    "source_scope_state_identity",
    "worker_authority_capsule"
  ],
  "produces": [
    "candidate_worker_contract",
    "candidate_result_envelope"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Candidate-Worker Contract

## Decision this card owns
Define and execute one isolated writable candidate slice without transferring controller, review, integration, or completion authority.

## Use when
- Admission produced one authorized isolated-write slice with a stable objective, disjoint write/resource set, and concrete verifier.

## Do not use when
- The slice is read-only, shares a canonical writer, needs unresolved user intent, lacks proof, or can publish/merge/close the workflow.

## Required inputs
- Goal/invariants, exact objective and completion criterion, revision/scope/state identity, dependency outputs, allowed reads/writes/resources, protected surfaces, side-effect ceiling, verifier/distinction, false-green risk, and required return schema.

## Procedure
1. Project only the bounded capsule; preserve authority, invariants, objective, scope, and proof before optional history when trimming context.
2. Use only operations/capabilities exposed by the active host and stay within nesting, path, resource, and side-effect ceilings.
3. Re-observe relevant state, implement the smallest coherent candidate in the assigned write set, and never overwrite unrelated or concurrent work.
4. Apply the assigned behavior distinction and focused verifier; record original command/status and treat unavailable/baseline/environment failures honestly.
5. Stop on stale identity, scope ambiguity, overlapping work, required authority expansion, unexpected external effects, or verifier invalidation.
6. Return touched files/artifacts, actual diff/candidate identity, commands/statuses, evidence refs, side-effect handles, assumptions, blockers, and unresolved questions.
7. Never self-approve, integrate into a canonical shared artifact, modify review criteria, claim remote success without a handle, or claim task/workflow completion.

## Output contract
- Revision-bound candidate result envelope containing slice ID, observed identity, touched set, candidate hash/path, proof evidence, side effects, deviations, unresolved items, status, and controller-validation needs.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop after producing or safely failing one isolated candidate. Do not load review orchestration or perform controller integration.
