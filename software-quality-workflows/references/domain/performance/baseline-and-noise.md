---
{
  "card_id": "sqw.domain.performance.baseline-and-noise",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "performance_symptom_and_result_identity",
    "representative_environment",
    "measurement_evidence"
  ],
  "produces": [
    "stable_performance_baseline"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 4096,
  "neighbors": [
    {
      "edge_id": "performance-to-optimization",
      "to_card_id": "sqw.domain.performance.optimization-and-parity",
      "edge_mode": "hard",
      "hard_predicate_id": "performance-baseline-stable",
      "missing_decision": "Stable baseline identifies a bottleneck but optimization/parity is unresolved",
      "required_evidence": "Representative method, sample/noise budget, bottleneck evidence, and frozen result identity",
      "evict_when": "Optimization and parity artifact recorded"
    }
  ]
}
---
# Performance Baseline and Noise

## Decision this card owns
Establish a representative, repeatable baseline and decide whether evidence identifies a stable bottleneck worth optimizing.

## Use when
- Latency, throughput, memory, bundle/startup/import/I/O/cache/query/rendering, or workflow runtime is a claimed problem.

## Do not use when
- No observable symptom/result contract exists or the request is to implement an already-frozen optimization.

## Required inputs
- User/operator-visible symptom, invariant result identity, representative inputs/environment/build/warm-cold state, candidate measurement method, raw samples, budgets, and authority/trade-off ceiling.

## Procedure
1. Freeze outputs, ordering, errors, state/persistence, determinism, side effects, and approved tolerances that performance work must preserve.
2. Select evidence matching the symptom: request spans/query/serialization; saturation/pools; tail/queue/locks/GC/retries/cold start; browser waterfall/trace; per-stage counts/I/O/cache; heap/allocation/retention.
3. Run equivalent inputs/environments/build modes with setup versus steady-state and warm versus cold separated where material.
4. Use enough repetitions to expose noise; retain raw results, sample count, invalid classifications, exact harness/command, uncertainty, and environmental differences.
5. Identify one bottleneck from profile/trace/plan/allocation/waterfall/stage evidence; classify timeouts, throttling, cache misses, and background load before blaming product logic.
6. Emit `stable` only when method/noise budget supports comparison and measured cause justifies intervention; otherwise emit inconclusive with the smallest missing evidence.

## Output contract
- Symptom/result identity, environment/input/method, raw evidence ref, samples/noise/uncertainty, bottleneck or inconclusive reason, trade-off ceiling, rollback baseline, and `next_edge_id|null`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `performance-to-optimization` | Stable baseline identifies a bottleneck but optimization/parity is unresolved | Representative method, sample/noise budget, bottleneck evidence, and frozen result identity | `sqw.domain.performance.optimization-and-parity` | Optimization and parity artifact recorded |

## Stop
Stop at a stable baseline/bottleneck or precise inconclusive result; do not optimize noisy or incomparable evidence.
