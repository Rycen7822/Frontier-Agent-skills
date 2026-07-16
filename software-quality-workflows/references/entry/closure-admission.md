---
{
  "card_id": "sqw.entry.closure-admission",
  "card_version": 1,
  "kind": "entry",
  "consumes": [
    "closure_admission_facts",
    "authority_projection",
    "scope_projection",
    "environment_projection"
  ],
  "produces": [
    "closure_admission_artifact"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Closure Admission

## Decision this card owns
Collect and transport the bounded facts needed by the machine Admission policy without creating a closure workflow or substituting model judgment for its three decisions.

## Use when
- The controller explicitly projects this card to audit or transport a disputed/malformed Admission fact/result boundary.

## Do not use when
- Router has returned normal card-free `ASSESS_CLOSURE`; the canonical machine evaluator needs no model card.
- Admission already produced a fresh valid bound artifact, or ordinary Direct/diagnosis/intent routing has precedence.

## Required inputs
- Machine-observable outcome, requirement stability, scope/authority freezability, environment reproducibility, verifier-qualification feasibility, side-effect bounds, closure value, framework tax, and their evidence refs.

## Procedure
1. Preserve unknown and disproven facts; never coerce missing high-risk evidence to `false` or feasible.
2. Invoke the canonical Admission evaluator with the exact fact projection and retain its original decision/reason codes.
3. Transport only `DIRECT_SELECTED -> ROUTE_STANDARD`, `CLOSURE_ELIGIBLE -> COMPILE_CLOSURE_CONTRACT`, or `TERMINAL -> EMIT_TERMINAL`.
4. For Direct, return the Admission artifact to Router; create no Closure Contract, workflow, or terminal certificate.
5. For Eligible, hand the artifact to Writing Plans compile/freeze; create no SQW workflow before a valid frozen execution handoff.
6. For Terminal, permit only `SPEC_UNDERDETERMINED`, `SPEC_UNSAT`, `AUTHORITY_BLOCKED`, `ENVIRONMENT_UNAVAILABLE`, `VERIFIER_UNQUALIFIABLE`, or `SIDE_EFFECT_UNBOUNDED`.
7. Treat an unqualified verifier as an execution concern. Use `VERIFIER_UNQUALIFIABLE` only when feasibility within current authority, environment, and budget is disproven.
8. Never widen authority, lower safety conditions, or turn Admission into a durable execution phase.

## Output contract
- Exact `closure_admission_artifact`: decision, next action, reason codes, terminal status if applicable, bound input/evidence identity, and no workflow ID/state version.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at the pre-workflow artifact boundary. Model output cannot create workflow state, compile/freeze a contract, accept a phase, or emit an execution terminal.
