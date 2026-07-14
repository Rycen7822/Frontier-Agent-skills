# Observability Instrumentation

Use this reference for services, APIs, workers, schedulers, queues, provider calls, long-running jobs, data pipelines, deployment health, or any behavior future operators must diagnose.

For request mode and side effects, follow the [authority and scope owner](authority-and-scope.md). For trust-boundary analysis and sensitive-data controls, follow [security hardening](security-hardening.md). For cross-feature performance baselines and optimization claims, follow [performance optimization](performance-optimization.md). For the required landing evidence, follow [verification discipline](verification-discipline.md). This reference owns signal design, telemetry failure isolation, telemetry-specific overhead budgets, and telemetry safety.

## Workflow

1. Write two to four concrete questions an operator will ask when the behavior fails or slows down.
2. Map each question to the smallest useful signal: metrics for aggregate amount and latency, traces for path and timing, logs for case explanation, health for service state, and checkpoints for long work.
3. Instrument ownership boundaries: request entry, queue transitions, dependency calls, storage changes, retries, cancellation, and irreversible side effects.
4. Propagate correlation across the boundaries that an operator must join.
5. Allowlist telemetry fields and define retention or sampling where volume or sensitivity warrants it.
6. Define bounded buffering, timeout, retry, backpressure/drop, and degradation behavior for a slow or unavailable telemetry backend; set latency, CPU, memory, and network budgets.
7. Trigger a representative success, product failure, telemetry-backend failure, and overload condition as applicable; prove the signal is useful without making the product path unbounded or unexpectedly unavailable.

## Signal design

| Signal | Good shape | Common failure |
|---|---|---|
| Structured log | Stable event name, bounded fields, correlation identifier, error class/code, and safe state. | Prose-only records, payload dumps, or missing correlation. |
| Metric | Counter, histogram, or gauge with units and bounded labels. | Unbounded labels, averages hiding tails, or unclear environment. |
| Trace/span | Boundary-level duration, status, dependency identity, and parent context. | Sensitive attributes or helper-level noise. |
| Health/readiness | Role-specific semantics for ready, degraded, and unavailable states. | A permanently green endpoint that ignores critical dependencies. |
| Progress/checkpoint | Started, completed units, partial failure, cancellation, and completion. | Silent work with only a final message. |

## Cardinality and privacy

- Prefer bounded categories such as route template, status class, operation type, dependency, version, and environment.
- Do not use user identifiers, request identifiers, arbitrary paths, raw URLs, exception text, prompts, documents, or payloads as metric labels.
- Redact or omit credentials, cookies, private content, and full personal data from every signal.
- Keep diagnostic identifiers opaque and scoped; do not expose full internal identifiers when a short correlation token suffices.
- Treat model, tool, browser, and dependency output as untrusted before logging it.

## Failure isolation and overhead

- Keep telemetry off a product-critical synchronous path unless the contract explicitly requires durable audit delivery; document any intentional fail-closed case.
- Bound queues, batches, buffers, cardinality, retry count, and exporter timeouts. Never trade a backend outage for unbounded memory growth or worker exhaustion.
- Choose and document what happens when capacity is exhausted: drop with a counter, sample, shed lower-priority detail, spool within a bounded durable budget, or reject the product action when a named audit invariant requires it.
- Preserve cancellation and shutdown semantics. Flush only within a bounded deadline and report discarded or undelivered telemetry honestly.
- Measure instrumentation overhead against a representative uninstrumented or previous baseline when the hot path, payload volume, or exporter changes materially.
- Exercise a slow, failing, and unavailable exporter or backend. Prove the product behavior matches the documented fail-open/fail-closed contract and that the degradation itself remains observable.

## Verification checklist

- Operator questions precede instrumentation choices.
- Each critical failure mode has a detectable signal and an owning response path.
- Correlation survives the boundaries needed for diagnosis.
- Latency uses a distribution when tail behavior matters.
- Retries, fallbacks, cancellations, and partial success are distinguishable.
- Mission-critical field semantics are tested or smoked without relying on incidental prose.
- A slow, unavailable, or saturated telemetry backend cannot cause unbounded blocking, memory, retries, or shutdown delay; any intentional fail-closed behavior is contract-tested.
- Instrumentation overhead remains inside its declared latency, CPU, memory, storage, and network budget.
- Changed metric semantics are reflected in the consuming alert, dashboard, or runbook when those consumers are in scope.

## Pitfalls

- More logs can increase cost while hiding the useful signal.
- High-cardinality labels can make a healthy code path operationally unsafe.
- A health check that tests only process liveness can misrepresent readiness.
- Instrumentation that cannot answer a named operator question is usually noise.
- An unbounded exporter queue or synchronous backend call can turn an observability outage into a product outage.
