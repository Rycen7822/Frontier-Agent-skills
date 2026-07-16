---
{
  "card_id": "sqw.domain.performance.optimization-and-parity",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "stable_performance_baseline",
    "measured_bottleneck",
    "frozen_result_identity"
  ],
  "produces": [
    "result_preserving_optimization_artifact"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Performance Optimization and Parity

## Decision this card owns
Change one measured owner seam, prove result parity, and report an honestly comparable performance delta and resource trade-offs.

## Use when
- Baseline/noise is stable and identifies one bottleneck whose expected value exceeds intervention complexity.

## Do not use when
- Baseline is noisy/incomparable, result identity is unfrozen, or the bottleneck no longer justifies change.

## Required inputs
- Stable baseline/method/raw evidence, measured bottleneck/owner, result parity matrix and independent oracle, authority/trade-off limits, candidate intervention, and rollback save point.

## Procedure
1. Prefer removing repeated work/ownership mistakes before caches; bound data with projection/pagination/stream/filter/limits and distinguish cold/hot paths.
2. Change only the owning seam with the smallest intervention. Caches require owner/key/size/invalidation/fallback/observable hit-miss; concurrency requires independence/order/cancel/limits/quotas.
3. Keep baseline and candidate independently executable. Canonical fixture/invariant/implementation is the oracle; a faster cache/model/backend/approximation cannot approve itself.
4. Rerun the same method/input/environment and prove parity for public output/order/errors/state/determinism/side effects plus approved tolerances.
5. Report before/after, samples, noise/confidence, invalid runs, and changed CPU/memory/I/O/latency/complexity trade-offs; distinguish measurement from inference.
6. Add a regression threshold only when recurrence is plausible and measurement reliable; retain reversibility and stop on parity ambiguity or shifted bottleneck.

## Output contract
- Intervention/owner, parity matrix/evidence, comparable before/after samples and uncertainty, resource trade-offs, threshold decision, rollback point, cleanup, residual risk and blockers.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at result-preserving measured evidence; never trade correctness, privacy, compatibility, or diagnosability for unapproved speed.
