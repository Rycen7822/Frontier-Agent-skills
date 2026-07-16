---
{
  "card_id": "sqw.diagnosis.reproduce-and-bound",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "diagnosis_contract",
    "runtime_evidence",
    "source_identity",
    "safe_probe_authority"
  ],
  "produces": [
    "reproduction_record",
    "failure_boundary"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Reproduce and Bound

## Decision this card owns
Determine whether the reported symptom reproduces and bound the smallest observed failure surface.

## Use when
- No fresh reproduction and failure boundary exist for the current source and environment.

## Do not use when
- The task is a static audit or a fresh equivalent record already exists.

## Required inputs
- Symptom, trigger, expected/observed behavior, source revision, environment, and safe probe authority.

## Procedure
1. Capture the complete error, stack, original exit status, immediately relevant logs, exact trigger, expected behavior, and observed behavior.
2. Select the narrowest symptom-specific loop that reaches the real boundary: focused test, CLI/API/UI path, replay, property harness, differential comparison, or revision bisection.
3. Preserve the original reproduction unchanged as a control. Minimize only a copy, removing one input, step, configuration, dependency, timing, or concurrency factor at a time and proving the same failure mechanism remains.
4. Separate product failure from setup, fixture, import, harness, permission, environment, and baseline failure. A command that never reaches the target is not its reproduction.
5. Inspect history and the dirty/concurrent worktree read-only. Treat current work as evidence and protected state.
6. Compare input, output, configuration, state/store identity, and error transformation at each relevant boundary; trace the bad value to the earliest actual/expected divergence.
7. Compare a working path governed by the same contract and record every material difference before judging relevance.
8. For nondeterminism, declare a bounded trial/time budget and decision rule, then record trials, failures, rate, and controlled variables. Prefer external or task-scoped probes; persistent product instrumentation is a separate authorized change with proof and privacy review.
9. Emit a fresh bounded reproduction record or typed `INCONCLUSIVE` with the unreachable boundary and evidence limit.

## Output contract
- `reproduced`, `classification`, `original_reproduction`, `minimized_reproduction|null`, `trigger`, `expected`, `observed`, `source_environment_identity`, `failure_boundary`, `boundary_observations`, `working_path_differences`, `repeatability`, `trial_budget`, `evidence_refs`, and `blocker|null`.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at the artifact boundary; Router decides whether hypothesis discrimination is next.
