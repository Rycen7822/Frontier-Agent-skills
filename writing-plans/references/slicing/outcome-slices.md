---
{
  "card_id": "wp.slicing.outcome-slices",
  "card_version": 2,
  "kind": "procedure",
  "decision_id": "wp.select.slicing.outcome-slices",
  "required_artifact_ids": ["plan-program"],
  "produced_artifact_ids": ["outcome-slices"],
  "max_bytes": 8192
}
---
# Outcome Slices

## Decision this card owns
Form typed, independently judgeable outcome slices and the current conflict-safe frontier from canonical decisions.

## Use when
- Handoff/Program needs dependencies, parallel-safety, migration order, or resumable outcome nodes.

## Do not use when
- A Brief is enough or design/intent/root cause remains unresolved.

## Required inputs
- Ready planning disposition; selected decisions/invariants; source/scope/authority; dependencies/effects/resources; acceptance/proof; and rollout/rollback.

## Procedure
1. Choose vertical, contract-first, risk-first, cleanup-first, compatibility, or verification-only shape by the observable result and risk—not file count.
2. Give each node one objective/completion criterion, stable inputs/outputs/dependencies, owner seam, allowed read/write/resource sets, effects/approval, proof distinction, false-green risk, and rollback/removal condition.
3. Split when required context cannot fit one bounded current-node projection or failure cannot be localized. Avoid horizontal layer batches that delay integration evidence.
4. Add typed control/data/evidence/invariant/effect/resource/approval edges and conservatively detect read/write/resource conflicts before calling nodes parallel-safe.
5. Compute the topologically ready current frontier; leave future fog coarse and candidate strategy exploration in SQW state, never canonical nodes.
6. If a slice crosses a turn, agent, or session, emit a schema-valid decision request for `wp.select.slicing.context-capsules` using the `outcome-slices` artifact; never invoke that card directly.

## Output contract
- One `outcome-slices` artifact containing typed nodes/dependencies, current frontier, conflict/exclusion reasons, proof/rollback, fog, and optional decision request.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop when each admitted slice is judgeable and the current frontier is conflict-safe or typed blocked.
