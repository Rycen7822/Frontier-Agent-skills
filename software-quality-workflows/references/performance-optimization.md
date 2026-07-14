# Performance Optimization

Use this reference for latency, throughput, memory, bundle size, rendering responsiveness, startup, imports, I/O, cache behavior, queries, or workflow runtime.

For request mode, scope, and acceptable tradeoffs, follow the [authority and scope owner](authority-and-scope.md). For completion evidence, follow [verification discipline](verification-discipline.md). This reference owns measurement and result-preserving optimization.

## Workflow

1. Define the user-visible or operator-visible symptom and the result that must remain equivalent.
2. Capture a baseline with representative input, environment, warm/cold state, and a repeatable method.
3. Identify one bottleneck from a profile, trace, query plan, allocation view, request waterfall, or stage timing.
4. Change the owning seam with the smallest intervention that addresses the measured cause.
5. Rerun the same method and prove behavioral or artifact equivalence.
6. Report before/after values, sample count, noise, confidence, and any changed resource tradeoff.
7. Add a stable regression threshold or signal only when recurrence is plausible and the measurement is reliable enough to enforce.

## Starting evidence

| Symptom | First evidence |
|---|---|
| One request path | Request timing, dependency spans, query log, serialization size. |
| Broad service slowdown | CPU, memory, pools, saturation, shared middleware, worker or event-loop state. |
| Intermittent latency | Tail percentiles, queue depth, locks, garbage collection, retries, and cold starts. |
| Initial page load | Network waterfall, server response, bundle and image size, blocking resources. |
| Interaction lag | Browser trace, long tasks, render churn, layout work, state derivation. |
| Batch or import | Per-stage timing, counts, I/O volume, concurrency, cache hit rate, checkpoints. |
| Memory growth | Heap or allocation snapshots, retained references, cache bounds, listener/task cleanup. |

## Change rules

- Remove repeated work or ownership mistakes before adding a cache.
- Bound data through pagination, projection, streaming, filtering, or explicit limits.
- Separate cold and hot paths when their constraints differ.
- Give every cache an owner, key contract, size bound, invalidation rule, fallback, and observable hit/miss behavior.
- Introduce concurrency only for independent operations; preserve ordering, cancellation, resource limits, and dependency quotas.
- Optimize the user-visible path rather than only a convenient micro-benchmark.
- Do not trade correctness, privacy, diagnosability, or compatibility for speed without explicit scope and evidence.

## Result-preserving decision contract

Before choosing an optimization mechanism, define the result identity that may not change and a parity matrix covering public outputs, ordering, error behavior, persistence/state, determinism, side effects, and any approved tolerances. Keep baseline and candidate independently executable until parity and rollback are proven. A faster approximation, cache hit, model, backend, or alternate implementation must not become the oracle for itself; use the canonical implementation, fixture, invariant, or independent comparison. Shadow measurements may observe but must not silently alter returned results. Change one bottleneck at a time, retain a reversible save point, and stop when parity is ambiguous, measurement is noisy, or the measured bottleneck no longer justifies the added mechanism.

`writing-plans` may order the slices and record the parity evidence required, but this reference remains the normative owner for baseline, bottleneck, parity, benchmark, and rollback policy.

## Benchmark discipline

- Compare equivalent inputs, environments, build modes, and warm/cold conditions.
- Separate setup time from steady-state time when both matter.
- Use enough repetitions to expose noise; report uncertainty instead of selecting the best run.
- Classify timeouts, throttling, cache misses, background load, and invalid samples before changing product logic.
- Preserve raw results outside chat when they are large, and keep the exact command or harness configuration traceable.

## Verification checklist

- A baseline exists from before the change.
- Evidence identifies the optimized bottleneck.
- Result or artifact parity covers the behavior that must remain unchanged.
- Before/after measurements use the same method and disclose meaningful differences.
- Cache, concurrency, batching, and skip paths remain bounded and observable.
- The reported conclusion distinguishes measured improvement from an inference or noisy result.
