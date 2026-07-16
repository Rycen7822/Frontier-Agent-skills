---
{
  "card_id": "wp.closure.hard-constraints-and-corners",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "draft_closure_contract",
    "acceptance_runtime_evidence",
    "verifier_feasibility"
  ],
  "produces": [
    "constraint_corner_verifier_contract"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Hard Constraints, Corners, and Verifier Requirements

## Decision this card owns
Make every hard constraint, required semantic corner, and verifier requirement stable, executable, and source-bound.

## Use when
- A closure draft lacks complete constraint, corner, oracle, or verifier-requirement identities.

## Do not use when
- The gap is assumption/intent ambiguity, search/publication policy, or freeze identity.

## Required inputs
- Draft and source identities; authoritative requirements; interfaces/tests/runtime evidence; environment/authority limits; verifier-feasibility evidence.

## Procedure
1. Give each hard constraint a stable ID, source anchor, exact statement, affected scope, and referenced corners/verifiers.
2. Make pass/fail machine-observable. A hard constraint cannot be traded against a soft objective or weakened by a candidate.
3. Give each required corner a stable ID, rationale, environment, related constraints, fixture/input, oracle, and minimum coverage; include boundary, failure, migration, compatibility, and authority corners when material.
4. Give each verifier requirement an oracle class, qualification level, evidence shape, independence/protected-kernel needs, and false-green risks.
5. Distinguish missing evidence from infeasible proof. Conflicts or impossible constraints return a minimal certificate rather than a relaxed contract.
6. Record soft objectives separately with unique continuous lexicographic priority and deterministic tie-breaking.

## Output contract
- Stable constraint/corner/verifier-requirement records, soft-objective order, evidence gaps, and `unsat_certificate|null`.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop when every record is executable and source-bound, or a typed infeasibility/conflict certificate exists.
