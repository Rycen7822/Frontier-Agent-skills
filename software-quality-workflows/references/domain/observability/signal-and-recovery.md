---
{
  "card_id": "sqw.domain.observability.signal-and-recovery",
  "card_version": 2,
  "kind": "procedure",
  "decision_id": "sqw.select.domain.observability.signal-and-recovery",
  "required_artifact_ids": [
    "workflow-intake"
  ],
  "produced_artifact_ids": [
    "domain-observability-signal-and-recovery"
  ],
  "max_bytes": 8192
}
---
# Observability Signal and Recovery

## Decision this card owns
Design the smallest safe signals that answer named operator questions and prove decision-grade health, progress, cancellation, and recovery semantics.

## Use when
- Services, workers, queues, providers, jobs, pipelines, or deployments need changed telemetry or operational readiness/progress/recovery decisions.

## Do not use when
- Existing signals already answer the question and no operational decision contract changes.

## Required inputs
- `workflow-intake`; two to four operator questions; failure/slow paths; ownership/dependency/state boundaries; current consumers; sensitive fields; volume/cardinality/retention/sampling; backend degradation; overhead budget; role/health/progress/retry/cancel/recovery contract.

## Procedure
1. Map each question to the smallest signal: metric for aggregates/distributions, trace for path/timing, log for case explanation, health for state, checkpoint for long work.
2. Instrument entry, queue/state transitions, dependencies/storage, retries/cancel/partial/irreversible effects, and only necessary correlation. Define stable codes, units/distributions, bounded labels, spans, and safe state; reject prose-only noise, averages hiding tails, and permanently green health.
3. Allowlist/redact fields; never place user/request IDs, arbitrary paths/URLs, exception/prompt/document/payload content, secrets, private data, or untrusted external/model/tool/browser text in metric labels or unsafe logs.
4. Bound buffers, batches, queues, cardinality, retries, timeouts, network/storage, and flush; define drop/sample/shed/bounded-spool or named audit fail-closed behavior and make telemetry degradation visible.
5. Define role-specific `ready`, `degraded`, and `unavailable` from critical capabilities/dependencies, not process liveness. Define started/completed units, checkpoint identity/freshness/cadence, remaining/stalled/partial/cancel/terminal states, and safe resume/retry.
6. Distinguish retries, fallbacks, duplicates/replays, cancellation, partial success, discarded telemetry, and recovery transitions. Bind unhealthy/stalled signals to owning response, bounded escalation, and safe operator action.
7. Exercise representative success, product failure, slow/failing backend, overload, role health, progress, partial/cancel, recovery, and telemetry degradation without destructive live data; prove latency/CPU/memory/network plus shutdown behavior.
8. Verify consuming alerts/dashboards/runbooks when in scope and report untested environments/responses separately.

## Output contract
- One `domain-observability-signal-and-recovery` with question→signal map, schemas/correlation/allowlists, privacy/cardinality/retention/degradation/overhead proof, role health truth table, progress/checkpoint/terminal and cancel/retry/recovery transitions, response owners/escalations, consumer status, gaps, and cleanup.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at decision-grade evidence; more telemetry, liveness, status prose, or silent work never proves readiness/completion.
