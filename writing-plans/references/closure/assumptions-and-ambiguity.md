---
{
  "card_id": "wp.closure.assumptions-and-ambiguity",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "draft_closure_contract",
    "source_precedence_evidence",
    "material_ambiguities"
  ],
  "produces": [
    "assumption_ambiguity_contract"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Assumptions and Ambiguity

## Decision this card owns
Resolve, safely default, or certify each material assumption, source conflict, and semantic ambiguity in a closure draft.

## Use when
- Multiple semantics, contradictory authorities, or an unproved default can change contract meaning.

## Do not use when
- Only constraint observability, search budget, publication ceiling, or immutable freeze remains.

## Required inputs
- Draft, ordered authoritative sources, repository/runtime evidence, ambiguity IDs, authority ceiling, and reversibility/validation evidence.

## Procedure
1. Apply source precedence: explicit authorized request; controlling project policy; admitted external contract; current source/tests/schema/runtime facts; then conservative inference.
2. Record every assumption with stable ID, provenance, confidence, reversibility, affected constraints, and validation or rollback trigger.
3. Admit a default only when it is local, reversible, non-public, non-destructive, and inside authority. Never default credentials, destructive cleanup, consumer migration, external effects, or publication.
4. Compare materially distinct interpretations and counterevidence. Do not select model preference merely to continue.
5. Emit `SPEC_UNDERDETERMINED` with the smallest missing source-bound decision when no safe choice exists; emit `SPEC_UNSAT` with the minimal conflicting hard set when requirements cannot coexist.
6. Preserve resolved assumptions as intended-state evidence, never actual execution truth.

## Output contract
- Assumption/default records, resolved source conflicts, rejected interpretations, and `ambiguity_certificate|null` / `unsat_certificate|null`.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop when every material ambiguity is resolved or represented by the smallest typed certificate.
