# Diagnosis Evidence and Hypothesis

## Purpose
Reproduce and bound the symptom, then discriminate causal hypotheses until one cause is supported or evidence is inconclusive.

## Use when
- A diagnosis intake exists and no fresh supported cause is bound to the current source/environment.

## Do not use when
- The task is a static audit, the symptom cannot reach the target boundary, or a fresh supported cause already exists.

## Required inputs
- task context; exact symptom/trigger/expected/observed behavior; source/environment; existing patch; safe probe/process authority; working path; and trial/experiment budget.

## Procedure
1. Capture complete error/status/logs and run the narrowest real focused, CLI/API/UI, replay, property, differential, or bisection loop that reaches the target behavior.
2. Preserve the original reproduction unchanged as control. Minimize only a copy, one factor at a time, proving the same failure mechanism remains.
3. Separate product, setup, fixture, import, harness, permission, environment, baseline, and stochastic failures. Bind nondeterministic trials, failure rate, controlled variables, time/attempt budget, and decision rule.
4. Trace inputs, outputs, configuration, state/store identity, and error transformation to the earliest actual/expected divergence; compare a working path under the same contract.
5. Rank a small set of materially distinct causes. For each record boundary, support, disproof observation, unknowns, and confidence; activate one hypothesis and predict one controlled observation before testing.
6. Prefer the cheapest safe discriminator. Experimental patches are evidence, never the repair; retain failed evidence and revert only task-owned experimental changes.
7. Use a debugger only for a task-owned isolated process when a predicted breakpoint/watchpoint directly distinguishes named hypotheses. Capture minimal redacted values, bind source/process/trial identity, detach, and clean up.
8. Reassess ownership or request wider replanning when evidence exposes hidden/shared state, crosses components, or disproves the proposed seam.
9. Emit a supported cause only when the predicted causal boundary is observed and alternatives are materially weakened; otherwise emit typed `INCONCLUSIVE` with the minimal missing discriminator.
10. Controller returns diagnose-only closeout, planning handoff, or authorized Direct intake; this reference never implements the repair.

## Required result
- One `diagnosis-evidence-and-hypothesis` with reproduction/control, classification, failure boundary, working-path differences, hypothesis table, experiments/debugger observation, supported cause or `INCONCLUSIVE`, confidence, evidence refs, existing-work disposition, proof needs, and blocker.

## Stop
Stop at supported cause or bounded inconclusion; never promote an experiment into production code.
