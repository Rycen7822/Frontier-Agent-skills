---
{
  "card_id": "sqw.closure.verifier-qualification",
  "card_version": 1,
  "kind": "phase",
  "consumes": [
    "verifier_phase_projection",
    "qualified_baseline_projection",
    "frozen_contract_projection",
    "verifier_bundle_projection"
  ],
  "produces": [
    "verifier_qualification_proposal"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Verifier Qualification

## Decision this card owns
Determine whether the frozen verifier bundle is addressable, stable, discriminating, independent, protected, and sufficient for the contract risk floor.

## Use when
- Controller projects `VERIFIER_QUALIFYING` with a fresh qualified baseline and immutable verifier-bundle candidate.

## Do not use when
- Generic gate selection is the only need, baseline identity is stale, or candidate implementation has begun without a qualified bundle.

## Required inputs
- Frozen contract/source/scope/environment/epoch identity, baseline classifications, oracle and counterexample-adapter projections, protected surfaces, risk floor, qualification evidence, cost/timeout/noise bounds, and limitations.

## Procedure
1. Check every required oracle for addressability, repeatable stability, discrimination against known/plausible wrong behavior, and independence from candidate-controlled outputs.
2. Bind expected baseline, tolerance/noise, evidence schema, counterexample adapter, cost/timeout, authority, and limitations.
3. Prove candidate writers cannot change controller/policy files, protected tests, benchmarks, thresholds, goldens, holdouts, authority/publication policy, or verifier locks.
4. Treat candidate-added tests as supplementary until independently reviewed, sensitivity-tested, lifecycle-accepted, and promoted in a new verifier epoch.
5. Record skipped cascade tiers and reasons; unavailable or non-discriminating oracles cannot count as pass.
6. Propose qualified, typed unqualified/blocked terminal evidence, or plan revision when the contract cannot be verified under current authority and environment.
7. Do not modify the bundle, promote a candidate, accept a phase, or close the workflow.

## Output contract
- `verifier_qualification_proposal`: bundle ref/hash/epoch, per-oracle qualification, protected-surface proof, risk-floor coverage, limitations, disposition, and evidence refs.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop when any required oracle is unstable, non-discriminating, candidate-controlled, stale, unavailable, or below the risk floor; emit evidence rather than weakening qualification.
