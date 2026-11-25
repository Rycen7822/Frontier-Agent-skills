# Runtime and performance diagnosis

Use for latency, throughput, resource consumption, trace evidence or version-dependent failures.

Establish the relevant workload, actual result and baseline. Compare equivalent inputs, environment and result semantics; faster output with missing work is not an optimization. Locate the bottleneck before changing architecture. Use enough observations to distinguish a real effect from noise, without a fixed iteration quota.

Correlate traces with the actual operation, state and timestamps. Separate queueing from execution, aggregate from per-request behavior, and missing events from observed absence. Reuse existing logs and trace queries; collect more only for a specific causal gap. Do not default to converting formats or adding an observability system.

Check versions, launch/configuration sources, runtime resolution and caches where they affect behavior. Different declarations do not prove different live versions, and matching declarations do not prove the process loaded the expected code. Verify the actual consumer when that distinction matters.

If temporary instrumentation is needed, select the minimum signal, control overhead and sensitive data, and remove it or justify maintaining it after diagnosis. Keep readiness distinct from liveness and define healthy recovery in terms of the real operation. Treat provider or host failures as environmental until evidence establishes otherwise.
