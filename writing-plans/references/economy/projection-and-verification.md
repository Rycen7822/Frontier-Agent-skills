---
{
  "card_id": "wp.economy.projection-and-verification",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "output_classification_contract",
    "baseline_behavior_evidence",
    "artifact_storage_contract"
  ],
  "produces": [
    "projection_and_verification_plan"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Projection and Verification

## Decision this card owns
Define compact/full projections, lazy retrieval, durable resume state, freshness, and parity/size proof for result-preserving economy.

## Use when
- Field classes are fixed and an implementation plan must preserve actionability while moving bulky state out of default context.

## Do not use when
- The selected output class or quality-critical consumer contract remains unknown.

## Required inputs
- Classified fields, representative baselines/goldens, consumers, protected anchors, storage/retrieval capabilities, compatibility contract, and sensitive-data rules.

## Procedure
1. Define each output profile and exact protected anchors; debug/full retains diagnostics removed from compact mode.
2. Move bulky state to bounded artifacts, log digests, checkpoints, indexes, or versioned docs with resolvable ID/path/hash/size and explicit on-demand reads.
3. Define resume material: current checkpoint/delta, artifact index, validation state, next action, blockers, and staleness/invalidation binding.
4. Set budgets from measured representative envelopes and protected-anchor cost. Mandatory fields fail closed rather than truncate; optional omissions list IDs/pointers.
5. Compare old/new counts, keys, ordering/ranking, warnings, required actions, coverage, and quality-critical fields; request debug mode in tests that require full evidence.
6. Measure the actual high-level agent envelope, not an inner helper, and document any size regression with its quality reason.
7. Preserve behavior/compatibility gates and add representative size checks. Do not claim soak, long-run stability, or token savings beyond measured scope.
8. Define rollout and rollback, including stale literal/copied-plan removal that cannot be mistaken for current truth.

## Output contract
- Profile/projection specs, protected anchors, storage/lazy-load/resume/freshness contracts, compatibility/parity/size gates, measured baseline/target, rollout/rollback, and limitations.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop when compact output is measurably smaller or justified, fully actionable, and parity-verifiable without hidden mandatory omissions.
