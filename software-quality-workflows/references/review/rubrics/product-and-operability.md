# Product and Operability Rubric

## Purpose
Judge whether the change delivers its user outcome and remains safely diagnosable, ready, recoverable, and operable.

## Use when
- User-visible journeys or service/job/pipeline/operator failure, progress, recovery, rollout, or telemetry surfaces change.

## Do not use when
- No product or operator-observable contract changes, or API/accessibility/privacy/security is the actual specialist concern.

## Required inputs
- `review-tier`; frozen user outcome/journeys; changed dependencies/states; signal/privacy contract; health/readiness/progress/retry/recovery; dashboards/alerts; rollout evidence; and current revision.

## Procedure
1. Trace entry, success, error, empty, loading, cancellation, partial, recovery, and irreversible states; compare behavior/feedback/transitions to frozen requirements and established conventions.
2. Check cross-component dependencies for partial outcomes, stale state, misleading success, or irreversible user actions and require behavior-level evidence rather than implementation shape or screenshots alone.
3. Check structured event/state/cause, cross-boundary correlation, useful error class, redaction, levels/sampling, metric units/types/bounded labels, dashboard/alert migration, and traces without private payloads.
4. Distinguish health from readiness; check bounded retry/backoff/timeout/circuit, long-job progress/completion/cancel/partial failure, atomic queue/batch validation, smoke/rollback/canary/migration/recovery, and triggered data/model provenance.
5. Require focused evidence for semantics/correlation/cancel/redaction and emit only introduced/materially obscured user or operating risks. Unavailable deployment judgement is an evidence/owner need, not an inferred pass.

## Required result
- One `review-rubrics-product-and-operability` with zero or more user-journey or operability candidates, expected/observed state, signal/recovery evidence, cardinality/privacy/rollout limitations, impact/correction/confidence/blocking/verification, owner needs, and positive notes.

## Stop
Stop at review evidence; do not expand product scope, design signals, operate deployment, fix, or publish approval.
