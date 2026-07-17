---
{
  "card_id": "sqw.delegation.admission-and-contract",
  "card_version": 2,
  "kind": "procedure",
  "decision_id": "sqw.select.delegation.admission-and-contract",
  "required_artifact_ids": [
    "workflow-intake"
  ],
  "produced_artifact_ids": [
    "delegation-admission-and-contract"
  ],
  "max_bytes": 8192
}
---
# Delegation Admission and Contract

## Decision this card owns
Decide whether delegation has net value and define revision-bound read-only or isolated-write slice contracts without transferring controller authority.

## Use when
- `workflow-intake` permits delegation and independent slices can reduce latency or improve evidence separation.

## Do not use when
- Work is small, serial, shares mutable state or canonical writers, has unresolved intent/control flow, lacks acceptance proof, or delegation is unauthorized or unavailable.

## Required inputs
- `workflow-intake`; authority and mode; frozen source/scope/state identity; objective, frontier and invariants; dependencies; read/write/resource sets; effects and protected surfaces; acceptance verifier and false-green risk; and live host capabilities and limits.

## Procedure
1. Compare reliability, latency, and separation value with capsule, coordination, validation, and reconciliation cost. Keep work controller-local when delegation has no net value.
2. Reject unresolved dependencies, overlapping writes/resources, hidden shared mutable state, unfrozen shared schemas, ambiguous criteria, and slices requiring user decisions or authority expansion.
3. Bind every admitted slice to one source/scope/state identity and declare ID, objective, completion criterion, dependencies, allowed reads/writes/resources, side-effect ceiling, protections, verifier, return schema, and stop conditions.
4. Keep dependent and shared-writer work serial. Admit only `read_only` or `isolated_write`: read-only slices receive one non-overlapping evidence question, shared identity, coverage schema, evidence references, not-reviewed surfaces and no write authority; isolated-write slices receive a disjoint candidate set, dependency outputs, an exact behavior distinction, actual-diff and proof requirements.
5. Confirm only live host operations, schemas, nesting/count limits, and child capabilities. Do not invent tools, parameters, background-completion behavior, or child authority.
6. Require both slice kinds to stop on stale identity, overlap, scope ambiguity, verifier invalidation, unexpected external effects, or required authority expansion. The isolated-write contract requires the worker to re-observe state, implement the smallest coherent candidate only in its set, run the assigned verifier, and return slice/observed identity, touched set, candidate hash/path, original commands/statuses, evidence refs, side effects, deviations, unresolved items, status, and controller-validation needs.
7. Forbid workers from asking on the controller's behalf, changing criteria, overwriting unrelated work, integrating canonical artifacts, self-approving, publishing, or claiming task/workflow completion. Returned summaries and test claims are evidence proposals; emit admitted contracts, rejected/controller-local reasons, dependency order, capability limits, and fan-in rules.

## Output contract
- One `delegation-admission-and-contract` with revision-bound slice manifests, shared identity and result schema, kind-specific authority and exact result envelopes, dependency order, read/write/resource and protection sets, effects, verifiers, capability bounds, rejections, fan-in rules, and blocker.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop after admission and contract definition; do not dispatch, implement, validate results, integrate, review, publish, or complete the workflow.
