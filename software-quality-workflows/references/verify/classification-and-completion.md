---
{
  "card_id": "sqw.verify.classification-and-completion",
  "card_version": 2,
  "kind": "decision",
  "decision_id": "sqw.select.verify.classification-and-completion",
  "required_artifact_ids": [
    "workflow-intake"
  ],
  "produced_artifact_ids": [
    "verify-classification-and-completion"
  ],
  "max_bytes": 8192
}
---
# Verification Classification and Completion

## Decision this card owns
Classify non-passing gates and decide the strongest truthful scoped completion status supported by fresh evidence.

## Use when
- Gate records are available and a failure cause or completion/interim/blocked/inconclusive claim must be decided.

## Do not use when
- Required gates have not run, source/scope drift is unresolved, or implementation is still changing.

## Required inputs
- `workflow-intake`; verification plan and immutable gate records; exact failures/logs; expected distinctions; pre-change baseline; source/scope/environment; coverage/freshness; installed/public proof; reviews, async work, and blockers.

## Procedure
1. For each non-pass, reproduce only enough to classify `product_failure`, `harness_gap`, `environment_unavailable`, `permission_denied`, `baseline_failure`, or `stochastic_or_flaky`.
2. Confirm a product failure is owned by changed behavior, not syntax, import, fixture, adapter, stale install, missing capability, scanner candidate, or wrong environment. Prove validators can fail for the intended reason.
3. Compare exact baseline without laundering old failure into regression or new regression into noise. Record bounded retry count and variability; never average away correctness failure.
4. Route harness, environment, permission, baseline, and flaky results to their owner. Product changes require supported product-failure evidence.
5. Record every applicable gate's exact command/procedure, original result, identity, and evidence; list `not_run` and `not_applicable` separately and never name ad-hoc evidence as canonical suite success.
6. Require neutral-context provenance/version proof at installed or public layers. Source tests alone are insufficient for those claims.
7. Revalidate evidence after source, scope, environment, artifact, verifier, or coverage change. Separate baseline failures, warnings, flakiness, scoped regressions, and residual uncertainty.
8. Emit `completed` only when every required fresh record passes within scope and no blocker/review/async work remains; otherwise use `interim`, `blocked`, or `inconclusive` with pending items and safe next action.
9. Keep local technical completion separate from merge, publication, release, deployment, approval, and remote-write authority.

## Output contract
- One `verify-classification-and-completion` with per-failure cause/evidence/owner/action, scoped status, source/scope/environment, gate records, public proof, not-run/not-applicable items, baseline delta, coverage/freshness, pending work, residual uncertainty, and blocker.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop before a completed claim unless every required proof is fresh and passing; this artifact grants no external authority.
