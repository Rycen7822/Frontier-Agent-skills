# Performance Baseline and Parity

## Purpose
Establish a stable measured bottleneck, change one owner seam, and prove comparable result parity and trade-offs.

## Use when
- Latency, throughput, memory, startup/import, I/O/cache/query/rendering, bundle, or workflow runtime is a claimed problem.

## Do not use when
- No observable result contract exists, evidence is noisy/incomparable, or the optimization is already frozen elsewhere.

## Required inputs
- task context; symptom and frozen output/order/error/state/effect identity; representative inputs/environment/build/warm-cold state; raw samples/method/noise budget; bottleneck evidence; independent parity oracle; authority/trade-off ceiling; rollback save point.

## Procedure
1. Freeze result identity, approved tolerances, determinism, side effects, and rollback baseline before measuring.
2. Select evidence matching the symptom—spans/query/serialization, saturation/pools, tails/queues/locks/GC/retries/cold start, waterfall/trace, stage counts/I/O/cache, heap/allocation/retention—and separate setup/steady and warm/cold where material.
3. Run equivalent inputs/environments/build modes with enough repetitions to expose noise; retain raw results, sample count, invalid classifications, exact harness/command, uncertainty, and environmental differences.
4. Identify one bottleneck from profile/trace/plan/allocation/waterfall/stage evidence; classify timeout, throttle, cache miss, and background load before blaming product logic. Stop inconclusive when comparison is unstable.
5. Prefer removing repeated work/ownership mistakes before cache. Bound data by projection/pagination/stream/filter/limits; caches require owner/key/size/invalidation/fallback/hit-miss; concurrency requires independence/order/cancel/limits/quotas.
6. Change only the owning seam with the smallest intervention. Keep baseline and candidate independently executable; a faster cache/model/backend/approximation cannot approve itself.
7. Rerun the same method/input/environment and prove parity for public output/order/errors/state/determinism/effects plus tolerances.
8. Report before/after samples, noise/confidence, invalid runs, CPU/memory/I/O/latency/complexity trade-offs, inference versus measurement, threshold decision, rollback, and shifted bottlenecks.

## Required result
- One `domain-performance-baseline-and-parity` with symptom/result identity, environment/method/raw evidence, samples/noise/uncertainty, bottleneck, intervention/owner, parity matrix/evidence, comparable delta, resource trade-offs, threshold, rollback, cleanup, residual risk, and blocker.

## Stop
Stop on noisy evidence or parity ambiguity; never trade correctness, privacy, compatibility, or diagnosability for unapproved speed.
