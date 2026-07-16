---
{
  "card_id": "wp.slicing.context-capsules",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "canonical_plan_state",
    "current_frontier_node",
    "fresh_identity_projection"
  ],
  "produces": [
    "context_capsule_contract"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Context Capsules

## Decision this card owns
Specify a bounded generated projection for one current node without creating a second plan truth or truncating mandatory safety anchors.

## Use when
- A Handoff/Program slice crosses a turn, agent, or session and needs bounded resumable context.

## Do not use when
- Work stays in the current context or canonical plan/source identities are stale.

## Required inputs
- Canonical plan/state hash, source/scope/bundle identity, current node/dependencies, global invariants, decisions/evidence/gaps, authority/protected boundaries, proof, and closure identity when applicable.

## Procedure
1. Project only goal; current objective/completion; global invariants; fresh dependency outputs; source/scope/state hashes; owner/read-first seams; allowed reads/writes/resources/effects/approval; verifier/distinction/false-green; non-goals/fog/blockers.
2. For closure include contract ID/hash/epoch, relevant constraint/corner/verifier refs, authority ceiling, and protected paths. Accept only bounded SQW incumbent/hard-failure/budget projections.
3. Exclude full plan/contract/future graph, candidate/workflow history, raw logs/chat/source dumps, unrelated decisions, and raw sensitive values. Redact sensitive objects to controlled IDs.
4. Treat every mandatory field as indivisible: if it cannot fit, fail closed with required bytes/IDs; never truncate it. Include optional relevant evidence by priority, listing omitted IDs and on-demand pointers.
5. Bind card IDs/hashes, plan/contract/source identities, expiry, invalidation triggers, included/omitted IDs, and the self-excluding generated snapshot hash.
6. Rebuild from canonical state on freshness change; a capsule/context hash change never mutates canonical workflow or plan identity.

## Output contract
- `capsule_ref`, projection/source hashes, current node, mandatory bytes/IDs, included/omitted optional IDs, on-demand pointers, expiry/invalidation, and `blocker|null`.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop with a complete bounded projection contract or explicit over-budget/stale blocker; mandatory truncation is always zero.
