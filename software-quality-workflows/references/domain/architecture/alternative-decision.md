---
{
  "card_id": "sqw.domain.architecture.alternative-decision",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "architecture_contracts_and_constraints",
    "material_design_alternatives",
    "repository_evidence"
  ],
  "produces": [
    "architecture_alternative_decision"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 4096,
  "neighbors": [
    {
      "edge_id": "architecture-alternative-to-migration-proof",
      "to_card_id": "sqw.domain.architecture.migration-proof",
      "edge_mode": "semantic",
      "missing_decision": "Selected design needs staged migration or rollback proof",
      "required_evidence": "Selected boundary, consumer inventory, coexistence and reversibility constraints",
      "evict_when": "Migration and rollback proof contract recorded"
    }
  ]
}
---
# Architecture Alternative Decision

## Decision this card owns
Compare the status quo and materially different architectures, select the smallest evidence-supported design, and record why.

## Use when
- A high-cost, cross-cutting, hard-to-reverse boundary has at least two viable structural choices.

## Do not use when
- Options merely rename/move the same layers or repository evidence already rules all but one out.

## Required inputs
- Module/dependency contracts, status quo, at least two material alternatives, callers, constraints, risks, proof needs, and reversibility/migration facts.

## Procedure
1. Reject cosmetic variants; useful differences include direct composition versus owned facade, sync coordination versus message boundary, or centralized versus distributed policy.
2. Compare caller knowledge/change distribution; policy/state/failure/lifecycle ownership; compatibility/migration; trust/operations; measured performance; real-contract testability; and reversibility/deletion.
3. Choose the smallest design satisfying current evidence and state why each rejected option is materially worse under the same constraints.
4. Record uncertainty and a spike/decision blocker when evidence cannot support a safe choice; do not use generic pattern preference.
5. Use repository documentation conventions. Create a durable decision record only if costly/hard-to-reverse, surprising without context, and alternatives have material trade-offs.
6. Decide whether implementation requires coexistence, staged migration, rollback, and temporary-path removal proof.

## Output contract
- Status quo/options, evidence matrix, selected or blocked decision, rejected rationale, consequences, validation/reversal trigger, durable-record need, migration need, and `next_edge_id|null`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `architecture-alternative-to-migration-proof` | Selected design needs staged migration or rollback proof | Selected boundary, consumer inventory, coexistence and reversibility constraints | `sqw.domain.architecture.migration-proof` | Migration and rollback proof contract recorded |

## Stop
Stop at selection/blocker and one migration decision; do not implement or create documentation ceremony by default.
