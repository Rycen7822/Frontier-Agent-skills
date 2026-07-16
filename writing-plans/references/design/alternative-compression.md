---
{
  "card_id": "wp.design.alternative-compression",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "evidence_decision_ledger",
    "viable_strategy_families",
    "rollback_proof_evidence"
  ],
  "produces": [
    "selected_strategy_and_compression"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 4096,
  "neighbors": [
    {
      "edge_id": "alternatives-to-planning-gate",
      "to_card_id": "wp.design.planning-gate",
      "edge_mode": "hard",
      "hard_predicate_id": "alternatives-compared",
      "missing_decision": "Compared alternatives have not passed the planning gate",
      "required_evidence": "Selected/rejected strategies, compression, proof, rollback, and residual fog",
      "evict_when": "Planning disposition is emitted"
    }
  ]
}
---
# Alternative Compression

## Decision this card owns
Compare materially distinct strategies, select or retain a family, and force an explicit non-append-only action for prior design.

## Use when
- Evidence leaves two or more viable strategy families or a proposed addition may duplicate/avoid an existing owner seam.

## Do not use when
- Evidence already leaves one defensible family; record that closure reason in the ledger.

## Required inputs
- Evidence/decision ledger, status quo, viable families, counterevidence, owner/contract impacts, reversibility, proof, migration, and rollback.

## Procedure
1. Compare status quo and materially different families by semantic fit, owner/dependency shape, blast radius, reversibility, proof quality, compatibility, and long-term burden.
2. For affected baseline decisions choose `keep`, `rewrite`, `split`, `merge`, `defer`, `delete`, or `replace`, with why the result is not avoidable append-only code.
3. Require new files/abstractions/dependencies/APIs/modes to explain why the owning seam cannot be changed, reused, merged, or removed instead.
4. Preserve counterevidence and reject cosmetic variants. Add a design round only when new evidence changes a decision, proof, rollback, or blast radius.
5. Select one family or emit a bounded underdetermination; name rejected families and empirical validation boundary.

## Output contract
- Selected/retained family, rejected alternatives, compression actions, consequences, proof/false-green plan, migration/rollback, residual fog, and `next_edge_id`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `alternatives-to-planning-gate` | Compared alternatives have not passed the planning gate | Selected/rejected strategies, compression, proof, rollback, and residual fog | `wp.design.planning-gate` | Planning disposition is emitted |

## Stop
Stop on an evidence-backed family or typed underdetermination; never select merely to keep planning moving.
