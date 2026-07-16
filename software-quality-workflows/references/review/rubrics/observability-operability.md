---
{
  "card_id": "sqw.review.rubrics.observability-operability",
  "card_version": 1,
  "kind": "rubric",
  "consumes": [
    "operational_change_projection",
    "failure_recovery_projection",
    "telemetry_evidence"
  ],
  "produces": [
    "observability_operability_findings"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Observability and Operability Rubric

## Decision this card owns
Judge whether changed services/jobs/pipelines remain safely diagnosable, observable, ready, recoverable, and operable.

## Use when
- APIs/services/workers/schedulers/tool calls/long jobs/deployment or ML/data production paths change.

## Do not use when
- No operator-visible failure/progress/recovery surface is implicated or this is an offline experiment with no production claim.

## Required inputs
- Scoped path/call flow, signal contracts, privacy/classification, health/readiness/progress/retry/recovery behavior, dashboards/alerts, rollout evidence, and current revision.

## Procedure
1. Check structured event/state/cause, correlation across boundaries, useful error class, redaction, levels, and sampling.
2. Check metric names/units/types, bounded labels, migrated dashboards/alerts, trace latency/failure/correlation without private payloads.
3. Check health versus readiness, bounded retry/backoff/timeout/circuit behavior, long-job progress/completion/cancel/partial failure, and atomic queue/batch validation.
4. Check proportionate smoke/rollback/canary/migration/recovery and, when triggered, data quality/model version/drift/output provenance.
5. Require focused evidence for fields/semantics/correlation/cancel/redaction, not incidental wording.
6. Emit only introduced/materially obscured operating risks; unavailable deployment judgment is a non-code evidence/owner need.

## Output contract
- Operability finding candidates, signal/recovery evidence, cardinality/privacy risks, rollout limitations, qualified-decision needs, and positive notes.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at review evidence; do not design signals, operate deployment, or publish approval.
