---
{
  "card_id": "sqw.closure.baseline-qualification",
  "card_version": 1,
  "kind": "phase",
  "consumes": [
    "validated_plan_execution_handoff",
    "baseline_phase_projection",
    "source_environment_projection",
    "authority_projection"
  ],
  "produces": [
    "baseline_qualification_proposal"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Baseline Qualification

## Decision this card owns
Determine whether the frozen contract has a stable, source-bound execution baseline that can support verifier qualification and candidate comparison.

## Use when
- Controller projects the current durable closure phase as `BASELINING` after validating a frozen Writing Plans handoff.

## Do not use when
- Admission or contract compilation is pending, the handoff is invalid/stale, or another durable phase is current.

## Required inputs
- Contract/plan/handoff identity, source/scope/environment fingerprints, public and installed entrypoints, required gates and corners, observed target/unrelated failures, external availability, noise/flakiness budget, protected surfaces, and baseline artifact schema.

## Procedure
1. Verify the projected contract, plan, policy, authority, source, scope, and environment identities before running baseline observations.
2. Exercise the real required entrypoints without candidate changes and preserve original command/status/evidence identity.
3. Classify target, unrelated, baseline, harness, environment, permission, external-availability, and stochastic failures separately.
4. Measure repeatability/noise under a declared budget and record a decision rule; absence in one rerun is not stability.
5. Freeze known failures, thresholds, public/install surfaces, artifact hashes, limitations, and evidence sensitivity.
6. Propose `qualified`, a typed blocker/terminal candidate, or `PLAN_REVISION_REQUEST` when new facts invalidate the frozen specification.
7. Do not mutate the contract, accept a transition, or start candidate work.

## Output contract
- `baseline_qualification_proposal`: bound identities, observations, classifications, stability/noise result, baseline artifact refs/hash, limitations, proposed disposition, and evidence refs.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop with a typed proposal when the baseline is unstable, environment unavailable, identity stale, or plan assumptions fail; never self-transition to verifier qualification.
