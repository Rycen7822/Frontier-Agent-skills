---
{
  "card_id": "wp.design.planning-gate",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "design_depth_decision",
    "evidence_decision_ledger",
    "selected_strategy_and_compression"
  ],
  "produces": [
    "planning_disposition"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Planning Gate

## Decision this card owns
Decide whether design evidence is ready for plan slicing, needs a spike/source/intent repair, or must stop with a typed blocker.

## Use when
- D1/D2 evidence and any required alternatives/compression decision are complete enough to judge readiness.

## Do not use when
- Source inspection or alternative comparison is still actively incomplete.

## Required inputs
- Depth and closure reason; source freshness; owner/contract/decision coverage; compression; proof/false-green; migration/rollback/approval; fog and blockers.

## Procedure
1. Confirm depth matches observable risk and relevant owners/contracts are grounded.
2. Confirm every material owner/seam decision and retained assumption has discriminating proof, false-green risk, and rollback/removal condition.
3. Reject avoidable append-only design, missing counterevidence, stale sources, or prose-expanded gaps.
4. For autonomous closure, ensure every admitted strategy family and lexicographic objective is explicit; material contract change requires a new epoch.
5. Emit exactly one disposition: `ready_for_slicing`, `spike_required`, `sqw_diagnosis`, `sqw_intent`, `source_required`, `approval_blocked`, `spec_underdetermined`, or `spec_unsat`.

## Output contract
- One disposition with design artifact ID/hash, selected rows, source/scope identity, global invariants, unresolved fog, blocker/evidence refs, and next-owner handoff.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at one evidence-backed disposition; this gate does not implement or claim execution completion.
