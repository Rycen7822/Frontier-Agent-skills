# Observability and Operability Review

Load this rubric for services, APIs, workers, schedulers, tool calls, long-running jobs, deployment behavior, or ML/data pipelines that future operators must diagnose and recover.

Use `references/review-result-schema.md` for findings. Use `references/observability-instrumentation.md` for implementation guidance and `references/verification-discipline.md` for evidence selection; this rubric does not duplicate those owners.

## Safe diagnostic signals

- Logs identify the event and important state with stable structured fields where practical.
- Correlation, request, run, session, job, or tool-call identifiers cross the boundaries needed to trace one failure.
- Errors retain useful class, state, and cause without dumping credentials, authorization material, raw prompts, user documents, arbitrary payloads, or private data.
- Log levels and sampling avoid both silent critical failures and operational noise.

Treat sensitive telemetry exposure or a newly silent critical path as a material finding.

## Metrics and traces

- Names and units are unambiguous; counters, gauges, and distributions match the quantity.
- Labels are bounded. User IDs, raw paths, prompts, arbitrary error text, and other unbounded values do not become dimensions.
- Existing dashboards and alerts are migrated when names or semantics change.
- Meaningful external calls and long operations preserve latency, failure status, and correlation without placing private payloads in trace attributes.

High-cardinality signals that can overload the backend, or loss of a critical health signal without replacement, warrant a finding grounded in the affected operating path.

## Health, readiness, progress, and recovery

- Health reflects the service role; readiness distinguishes startup from safe service when necessary.
- Retry, backoff, timeout, and circuit behavior is bounded and observable.
- Long jobs expose progress, completion, cancellation, and partial-failure state without leaving callers waiting after state has changed.
- Queued or batched work avoids partial submission when the contract requires all-or-nothing validation.
- Risky rollout paths have a proportionate smoke, rollback, canary, migration, or recovery story.

Do not require every signal for every component. Focus on failure modes introduced or materially obscured by the change.

## ML and data signals

When triggered, check schema and data-quality failures, missing or late inputs, model latency/errors/version, drift or quality signals, and traceability from output to data/model/config revision. An offline experiment does not inherit all production monitoring requirements.

## Telemetry evidence

Important telemetry contracts may need focused checks for structured fields, success/failure metrics, correlation propagation, cancellation behavior, and redaction. Test fields and operator-visible semantics rather than incidental message wording.

Use observability or operability categories in the canonical schema. If a required operational judgment depends on unavailable deployment context, record a non-code-fixable evidence or owner decision instead of assuming safety.
