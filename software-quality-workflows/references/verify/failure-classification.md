---
{
  "card_id": "sqw.verify.failure-classification",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "failed_gate_run",
    "baseline_evidence",
    "environment_identity",
    "scope_identity"
  ],
  "produces": [
    "failure_classification"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Verification Failure Classification

## Decision this card owns
Classify a failed or unstable gate before any product change, retry, waiver, or completion decision.

## Use when
- A required or informative gate did not pass, was inconclusive, or disagrees with baseline evidence.

## Do not use when
- All required gates have fresh passing records and no stochastic or baseline ambiguity remains.

## Required inputs
- Original gate record and log, exact failed identifiers, expected distinction, pre-change baseline, environment identity, reproduction attempts, and scope/source binding.

## Procedure
1. Reproduce only enough to distinguish `product_failure`, `harness_gap`, `environment_unavailable`, `permission_denied`, `baseline_failure`, or `stochastic_or_flaky`.
2. Confirm that a claimed product failure is owned by the changed behavior and not syntax, import, fixture, adapter, stale install, missing capability, or wrong environment.
3. Treat scanner matches as candidates until contextual evidence proves a finding.
4. Prove a validator can fail for the intended reason; a permanently green self-check is not conformance evidence.
5. Compare against the recorded baseline without laundering a pre-existing failure into a new regression or a new regression into baseline noise.
6. Record retry count and observed variability; do not average away a correctness failure.

## Output contract
- `failure_classification`: gate ID, cause class, supporting and counterevidence refs, affected source/scope, retry observations, owner, and required next action.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop before modifying product code unless evidence supports `product_failure`; route harness, environment, permission, baseline, and flaky outcomes to their actual owner.
