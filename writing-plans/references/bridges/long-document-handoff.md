---
{
  "card_id": "wp.bridges.long-document-handoff",
  "card_version": 1,
  "kind": "bridge",
  "consumes": [
    "large_source_corpus",
    "planning_deliverable",
    "external_owner_availability"
  ],
  "produces": [
    "bounded_document_owner_handoff"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Long-Document Planning Handoff

## Decision this card owns
Hand a large multi-source planning corpus to its segmented-writing owner without importing that workflow or losing the software planning contract.

## Use when
- Source inventory, durable scratch, segmented drafting, rereads, and whole-draft repair exceed one bounded planning context.

## Do not use when
- The corpus is small enough for bounded repository evidence reads or the requested output is not a software plan/handoff.

## Required inputs
- Source inventory/identities, requested plan/profile/audience, canonical output/worknote location, authority, software decision questions, evidence/coverage expectations, and installed owner availability.

## Procedure
1. Route corpus management, source ledger, segmented drafting, recovery packets, and whole-draft review to the installed long-document segmented-writing owner when available and justified.
2. Pass only bounded planning requirements: profile, owner/contract questions, required evidence, source/scope identities, decision/gap ledger, and output path/authority.
3. Receive stable source/evidence pointers, coverage matrix, draft sections, conflicts, and unresolved gaps; do not duplicate its private orchestration in WP cards.
4. Reopen exact pointers only when a software owner, contract, freshness, proof, or rollback decision needs it.
5. If the external owner is unavailable, stop with a typed handoff blocker unless the corpus is demonstrably bounded for local segmented handling.

## Output contract
- External owner route, source/coverage/evidence projections, plan deliverable identity, unresolved software decisions, and `blocker|null`.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop without claiming corpus coverage when the external owner cannot run and a bounded fallback is not justified.
