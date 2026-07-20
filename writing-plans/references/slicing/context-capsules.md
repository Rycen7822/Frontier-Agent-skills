---
{
  "card_id": "wp.slicing.context-capsules",
  "card_version": 2,
  "kind": "procedure",
  "decision_id": "wp.select.slicing.context-capsules",
  "required_artifact_ids": ["outcome-slices"],
  "produced_artifact_ids": ["context-capsule"],
  "max_bytes": 8192
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
- Canonical plan/state hash, source/scope/bundle identity, current node/dependencies, global invariants, decisions/evidence/gaps, authority/protected boundaries, and proof.

## Procedure
1. Project only goal; current objective/completion; global invariants; fresh dependency outputs; source/scope/state hashes; owner/read-first seams; allowed reads/writes/resources/effects/approval; verifier/distinction/false-green; non-goals/fog/blockers.
2. Exclude full plan/future graph, candidate/workflow history, raw logs/chat/source dumps, unrelated decisions, and raw sensitive values. Redact sensitive objects to controlled IDs.
3. Treat every mandatory field as indivisible: if it cannot fit, fail closed with required bytes/IDs; never truncate it. Include optional relevant evidence by priority, listing omitted IDs and on-demand pointers.
4. The command wrapper supplies only node, consumer, budget, and strict runtime projection. The CLI derives card, manifest, and renderer hashes and stores the bounded runtime bytes only in the accepted `last_transition`.
5. Render once from candidate state in memory, commit exactly one semantic transition, then publish fixed `projections/context-capsule.md`. Exact replay repairs output loss; current-state rerender never changes state.

## Output contract
- One fixed context projection and receipt locator. State stores no projection locator/hash or metadata sidecar; later state advance makes the old context non-current and blocks rerender.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop with a complete bounded projection contract or explicit over-budget/stale blocker; mandatory truncation is always zero.
