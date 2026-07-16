---
{
  "card_id": "sqw.domain.observability.signal-design",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "operator_questions_and_failure_modes",
    "instrumentation_boundaries",
    "telemetry_safety_and_budget"
  ],
  "produces": [
    "observability_signal_contract"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 4096,
  "neighbors": [
    {
      "edge_id": "observability-to-health-progress",
      "to_card_id": "sqw.domain.observability.health-progress-and-recovery",
      "edge_mode": "semantic",
      "missing_decision": "New signals must support readiness, progress, or recovery decisions",
      "required_evidence": "Role/failure semantics, progress units, cancellation/partial/recovery states, and operator response",
      "evict_when": "Health/progress/recovery contract recorded"
    }
  ]
}
---
# Observability Signal Design

## Decision this card owns
Choose the smallest safe bounded signals that answer named operator questions across the ownership boundaries needed for diagnosis.

## Use when
- Services/APIs/workers/queues/providers/long jobs/pipelines/deployments need new or changed logs, metrics, traces, correlation, or telemetry delivery behavior.

## Do not use when
- Existing signals already answer the question or only readiness/progress/recovery semantics remain unresolved.

## Required inputs
- Two to four concrete operator questions, critical failure/slow paths, ownership/dependency/state boundaries, existing signals/consumers, sensitive fields, volume/cardinality/retention/sampling, backend failure contract, and overhead budget.

## Procedure
1. Map each question to the smallest signal: metric for aggregate amount/distribution; trace for path/timing; log for case explanation; health for state; checkpoint for long work.
2. Instrument request entry, queue/state transitions, dependency/storage calls, retries/cancel/partial/irreversible side effects and propagate only the correlation needed to join them.
3. Define stable structured events/codes, units/distributions, bounded labels, boundary spans, and safe state. Avoid prose-only logs, helper noise, averages hiding tails, and permanently green health.
4. Allowlist fields; never use user/request IDs, arbitrary paths/URLs, exception/prompt/document/payload content as metric labels; redact secrets/private data and treat external/model/tool/browser output as untrusted.
5. Bound buffers/batches/queues/cardinality/retries/timeouts/network/storage/flush. Specify drop/sample/shed/bounded-spool or named audit fail-closed behavior and keep degradation observable.
6. Exercise representative success, product failure, slow/failing/unavailable backend and overload; prove product behavior/cancel/shutdown plus latency/CPU/memory/network budget.
7. Record consumers requiring updated alert/dashboard/runbook semantics and whether readiness/progress/recovery remains a separate decision.

## Output contract
- Operator question→signal map, event/metric/span/correlation schema, boundary and field allowlist, privacy/cardinality/retention, backend degradation and overhead proof, consumer changes, gaps, and `next_edge_id|null`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `observability-to-health-progress` | New signals must support readiness, progress, or recovery decisions | Role/failure semantics, progress units, cancellation/partial/recovery states, and operator response | `sqw.domain.observability.health-progress-and-recovery` | Health/progress/recovery contract recorded |

## Stop
Stop at a bounded signal contract or one missing operational decision; more telemetry without a named question is not progress.
