---
{
  "card_id": "sqw.bridges.source-target-gap-audit",
  "card_version": 1,
  "kind": "bridge",
  "consumes": [
    "primary_source_identity",
    "target_identity",
    "audit_scope"
  ],
  "produces": [
    "source_target_gap_map"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Source-to-Target Gap Audit Bridge

## Decision this card owns
Route or perform a bounded read-only comparison between primary-source claims and a target's observable implementation, tests, and documentation.

## Use when
- A paper, specification, design, or authoritative document must be compared with a named code/product target.

## Do not use when
- The request authorizes implementation, asks for general synthesis, or lacks stable source and target identities.

## Required inputs
- Primary-source revision and access, target revision/surface, audit question, coverage projection, exclusions, and available paper/research/document owner.

## Procedure
1. Freeze source and target identities and keep paper/source claims distinct from target behavior and reviewer inference.
2. Prefer the relevant paper, research, or document audit owner when available; pass the bounded comparison contract rather than copying its full method.
3. For a bounded local fallback, extract claims, assumptions, conditions, and evidence from the primary source; do not substitute secondary summaries where primary evidence is available.
4. Map each claim to target implementation, tests, runtime evidence, and documentation, then classify it as implemented, partial, missing, contradicted, or not assessable.
5. Cite both source and target anchors, state coverage/not-reviewed surfaces, and rank gaps by impact and evidence strength.
6. Emit remediation recommendations separately from verified findings; do not edit the target.

## Output contract
- `source_identity`, `target_identity`, `coverage`, `claim_target_matrix`, `findings`, `evidence_refs`, `not_reviewed`, and `ranked_recommendations`.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop with `not assessable` rather than inferring equivalence when either side lacks primary evidence.
