---
{
  "card_id": "sqw.runtime.exit-and-escalation",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "runtime_stability_contract",
    "round_and_issue_ledger_projection",
    "current_gates_provenance_and_boundaries"
  ],
  "produces": [
    "runtime_stability_exit_or_escalation"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Runtime Stability Exit and Escalation

## Decision this card owns
Judge scoped confidence met, repeat required, repair reroute, external block, inconclusive stop, or authority/budget escalation from current round evidence.

## Use when
- Clean target, stop, blocked, budget, pending-work, product-issue, or escalation condition requires a terminal/control decision.

## Do not use when
- A round remains validly in progress or current source/runtime/evidence identity cannot be reconciled.

## Required inputs
- Frozen contract, round outcomes/clean count/issues/fixes, same-path reruns, required gate evidence, final source/active-runtime provenance, reached/excluded surfaces, pending processes/jobs/sessions, budgets/stops, authority, and unverified/external boundaries.

## Procedure
1. Reconcile source/scope/runtime identity and pending work; stale or background-pending state cannot support completion.
2. `confidence_met` requires real public task completion, required surfaces or explicit exclusions, every product issue fixed+activated+same-path verified or reported, valid focused/affected/public/canonical gates, final active provenance, clean target, and resumable durable state.
3. Select `repeat_required` only within current budget with no unresolved repair/authority boundary; each repeat uses a fresh projection.
4. Select `repair_reroute` for a supported product issue; `blocked_external` for environment/permission/cost/quota/service/authority; `inconclusive` for stale/incomplete/nondeterministic evidence.
5. Escalate rather than cross destructive/external/authority/budget boundaries; repeated reruns cannot wash out deterministic failure or unfavorable valid benchmark result.
6. Report real-runtime proof, code-test-only proof, unverified surfaces, baseline failures, and external blockers separately; confidence is scoped to declared task/product/environment/evidence.

## Output contract
- Decision/reason, round count/outcomes, issues/fixes/same-path proof, final identities, surfaces/gates, clean target, pending work, external/unverified/out-of-scope boundaries, escalation need, resumability state.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at a truthful scoped exit/reroute/escalation; never claim absolute or universal runtime reliability.
