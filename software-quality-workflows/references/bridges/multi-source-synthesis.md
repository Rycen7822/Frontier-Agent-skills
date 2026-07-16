---
{
  "card_id": "sqw.bridges.multi-source-synthesis",
  "card_version": 1,
  "kind": "bridge",
  "consumes": [
    "source_corpus",
    "synthesis_deliverable",
    "external_owner_availability"
  ],
  "produces": [
    "evidence_anchored_synthesis"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Multi-Source Synthesis Bridge

## Decision this card owns
Route a multi-source writing task to its document-synthesis owner, or admit only a bounded local fallback without importing that owner's full workflow.

## Use when
- Several source documents must become one evidence-anchored report, plan, guide, or other durable narrative artifact.

## Do not use when
- The task is ordinary code inspection, one small document, or source-target implementation auditing.

## Required inputs
- Source inventory and identities, requested deliverable and audience, authority boundaries, citation/evidence expectations, corpus size, and availability of a long-document synthesis owner.

## Procedure
1. Prefer the installed long-document segmented-writing/document-synthesis owner when corpus size, section count, or compaction risk justifies it; hand off source identities, deliverable, authority, and required evidence.
2. Accept its evidence ledger, coverage map, draft, and unresolved gaps as the bridge result; do not duplicate its private orchestration here.
3. Use a local fallback only for a demonstrably bounded corpus: keep a source ledger, extract claims by deliverable section, reconcile conflicts, draft in segments, and bind conclusions to source anchors.
4. Mark unread, inaccessible, conflicting, or weakly supported material explicitly and prevent unsupported synthesis from becoming fact.
5. Stop and escalate to the external owner when the fallback would exceed the active context or require repeated broad rereads.

## Output contract
- `owner_route`, `source_ledger`, `coverage_by_section`, `synthesis_artifact`, `evidence_refs`, `conflicts`, and `unresolved_gaps`.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop without pretending full coverage when source identity, corpus bounds, or evidence anchoring is unavailable.
