---
{
  "card_id": "wp.bridges.long-document-handoff",
  "card_version": 2,
  "kind": "bridge",
  "decision_id": "wp.select.bridges.long-document-handoff",
  "required_artifact_ids": [],
  "produced_artifact_ids": [
    "long-document-handoff"
  ],
  "max_bytes": 4096
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
- Source/scope identities, requested plan/profile/audience, canonical final-output location, authority, software decision questions, requirements, unresolved decisions, and installed owner availability.

## Procedure
1. Route corpus management, source ledger, segmented drafting, recovery packets, and whole-draft review to the installed long-document segmented-writing owner when available and justified.
2. Pass only bounded planning requirements: profile, owner/contract questions, required evidence, source/scope identities, unresolved decisions, final output path, and authority.
3. Receive only `scratch_retention`, the final locator and hash, source/scope identities, satisfied requirements, and unresolved decisions. Never copy sections, ledger, coverage, recovery, or confidence content into Writing Plans state.
4. Reopen the final locator only when a software owner, contract, freshness, proof, or rollback decision needs it. The scratch root remains private to its owner.
5. If the external owner is unavailable, stop with a typed handoff blocker unless the corpus is demonstrably bounded for local segmented handling.

## Output contract
- One `long-document-handoff` containing the external owner route, `scratch_retention`, final locator/hash, source/scope identities, requirements status, unresolved software decisions, and `blocker|null`. It is a delivery boundary, not an owner anchor.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop without claiming corpus coverage when the external owner cannot run and a bounded fallback is not justified.
