---
{
  "card_id": "wp.design.evidence-and-decision-ledger",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "design_depth_decision",
    "repository_evidence",
    "source_identity"
  ],
  "produces": [
    "evidence_decision_ledger"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 8192,
  "neighbors": [
    {
      "edge_id": "evidence-to-alternative-compression",
      "to_card_id": "wp.design.alternative-compression",
      "edge_mode": "semantic",
      "missing_decision": "Multiple viable strategy families remain",
      "required_evidence": "Baseline, decision, counterevidence, proof, and rollback rows",
      "evict_when": "Strategy family and compression actions are selected"
    }
  ]
}
---
# Evidence and Decision Ledger

## Decision this card owns
Ground each material owner/seam decision in bounded inspected evidence and a stable, non-duplicated ledger.

## Use when
- D1/D2 requires facts, decisions, proof, rollback, or compression ownership before slicing.

## Do not use when
- D0 is sufficient, or a large source corpus needs the external long-document owner first.

## Required inputs
- Depth/scope, source revision, controlling project instructions, relevant source/tests/config/types/history, requirements, and evidence pointers.

## Procedure
1. Inspect bounded owner/caller/test/config/contract evidence; use history only when regression, ownership, or compatibility needs it. Mark assumptions explicitly.
2. Record stable baseline/fact rows with element, current contract, source anchor, owner/seam, freshness, and change risk.
3. Record one decision row per material owner/seam/contract/proof move, with baseline refs, intent, touched seams, expected impact, rollback, and discriminating proof.
4. Record compression candidates against baseline rows; do not make every file/action a decision row or duplicate canonical state.
5. Record counterevidence, unresolved fog, false-green risks, and source gaps. Reopen exact pointers when freshness affects a decision.
6. Keep the artifact compact and task-owned; expose evidence and rationale, not private reasoning transcripts.
7. If several materially viable families remain, emit the alternatives edge; otherwise record why evidence excludes them.

## Output contract
- Depth/source identity; stable baseline/fact/decision/compression/proof rows; counterevidence; unresolved fog; closure reason; `next_edge_id|null`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `evidence-to-alternative-compression` | Multiple viable strategy families remain | Baseline, decision, counterevidence, proof, and rollback rows | `wp.design.alternative-compression` | Strategy family and compression actions are selected |

## Stop
Stop when all material decisions are evidence-bound or the smallest source gap is explicit.
