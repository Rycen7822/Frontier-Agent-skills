---
{
  "card_id": "sqw.domain.observability.health-progress-and-recovery",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "observability_signal_contract",
    "role_and_dependency_health_semantics",
    "long_work_state_contract"
  ],
  "produces": [
    "health_progress_recovery_artifact"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Health, Progress, and Recovery

## Decision this card owns
Define and prove role-specific readiness/degradation, long-work progress, cancellation/partial failure, and recovery decisions from bounded signals.

## Use when
- Operators or automation must decide ready/degraded/unavailable, progress/stall, cancellation, retry/recovery, or terminal completion.

## Do not use when
- Only low-level log/metric/span shape is unresolved or no operational decision consumes the signal.

## Required inputs
- Signal contract, service/worker/job roles and critical dependencies, state/event/checkpoint units, readiness and terminal invariants, retry/cancel/partial/recovery behavior, operator response, alert/dashboard/runbook consumers, and probe budget.

## Procedure
1. Define role-specific `ready`, `degraded`, and `unavailable` semantics from critical capabilities/dependencies rather than process liveness alone.
2. Define started/completed units, checkpoint identity/freshness, expected cadence, remaining/stalled/partial/cancel/terminal states, and what may safely resume or retry.
3. Make retries, fallbacks, duplicate/replayed events, cancellation, partial success, discarded/undelivered telemetry, and recovery transitions distinguishable.
4. Bind each unhealthy/stalled/recovery signal to an owning response path, bounded escalation, and safe operator action; do not let status text substitute for state evidence.
5. Trigger representative ready/degraded/unavailable, progress, partial/cancel, recovery and telemetry-backend degradation cases without destructive live data.
6. Verify consuming alerts/dashboards/runbooks when in scope and report any untested environment/response separately.

## Output contract
- Role health truth table, dependency/threshold/freshness rules, progress/checkpoint/terminal contract, cancel/partial/retry/recovery transitions, response owners/escalations, probe evidence, consumer status, gaps and cleanup.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at decision-grade health/progress/recovery evidence; never equate liveness, final prose, or silent work with readiness/completion.
