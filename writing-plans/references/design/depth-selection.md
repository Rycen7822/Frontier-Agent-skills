---
{
  "card_id": "wp.design.depth-selection",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "normalized_request",
    "design_risk_evidence",
    "owner_contract_evidence"
  ],
  "produces": [
    "design_depth_decision"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 4096,
  "neighbors": [
    {
      "edge_id": "depth-to-evidence-ledger",
      "to_card_id": "wp.design.evidence-and-decision-ledger",
      "edge_mode": "hard",
      "hard_predicate_id": "design-depth-needs-evidence",
      "missing_decision": "D1 or D2 evidence ledger is not formed",
      "required_evidence": "Risk, owner, contract, and source projection",
      "evict_when": "Evidence and decision rows are recorded"
    }
  ]
}
---
# Design Depth Selection

## Decision this card owns
Select D0, D1, or D2 from observable design risk and define the smallest required decision artifact.

## Use when
- A plan may alter ownership, add a seam, affect a shared/public contract, or make a costly-to-reverse choice.

## Do not use when
- Root cause or intended outcome is unresolved; return to SQW diagnosis/intent instead.

## Required inputs
- Normalized outcome/non-goals, current owner/contract evidence, reversibility, public/security/shared-state/migration risk, and viable-option evidence.

## Procedure
1. Choose D0 for a mechanical/local change whose owner/contract is already clear and adds no seam; record one sentence only.
2. Choose D1 for a plausible helper/adapter/cache/mode/schema/dependency/owner decision; require only relevant fact, decision, compression, proof, and rollback rows.
3. Choose D2 for public contracts, cross-module migration, security/shared state, hard-to-reverse architecture, or materially different viable options; require scoped alternatives, counterevidence, migration/rollback, and closure reason.
4. Never infer depth from file count, line count, or a generic complexity score.
5. Bind the decision to inspected source identity and name the evidence still required.

## Output contract
- `depth`, trigger/rationale, scoped decision artifact identity, required row classes, missing evidence, and `next_edge_id|null`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `depth-to-evidence-ledger` | D1 or D2 evidence ledger is not formed | Risk, owner, contract, and source projection | `wp.design.evidence-and-decision-ledger` | Evidence and decision rows are recorded |

## Stop
Stop at D0 or a bounded D1/D2 evidence contract; do not begin implementation design from assumptions.
