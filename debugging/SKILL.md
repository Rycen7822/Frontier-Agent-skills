---
name: debugging
description: "Diagnose unknown causes of bugs, regressions, failed checks, performance problems, or runtime traces. Use to identify a failure mechanism; a known-cause fix or simple verification does not need a full diagnosis."
license: MIT
metadata:
  version: 1.0.0
  hosts: [codex, hermes-agent]
---

# Debugging

Start with the observed failure, expected behavior and affected scope. Reuse existing logs, traces, reproductions and relevant baseline evidence. Preserve the failing state when collecting new evidence would destroy it. Diagnose only, or fix as well, according to the user's request.

Distinguish product failure from a mistaken expectation, harness/setup failure, environmental drift or an unrelated baseline problem. An unavailable dependency or provider timeout is not evidence of product behavior. A file outside the diff can still fail because of an indirect dependency.

Form the smallest causal hypothesis that explains the observation. Identify a discriminating observation or experiment: what result would reject it? Inspect the decisive premise, caller and state transition rather than patching symptoms. Check serialization, asynchronous ordering, caches and external implementations when they can invalidate that premise.

Run the cheapest useful discriminator. Avoid repeated unchanged failing commands; retry only when a changed input, setup, hypothesis or independent observation could alter the conclusion. If evidence remains insufficient, state the missing fact and bounded next step instead of accumulating retries.

For performance, traces or version inconsistencies, read [runtime diagnosis](references/runtime.md). Use existing representations and queries; do not convert every trace into a database or add telemetry infrastructure before it answers a real gap.

When a repair is authorized, fix the responsible owner and verify the affected behavior after the coherent change. Reuse valid protection. Add a durable regression test only when it guards a meaningful recurrence at reasonable maintenance cost; keep one-off probes temporary. Do not weaken an oracle to obtain a pass.

Report the cause and supporting observation, the repair if made, and what the final check establishes. Distinguish a confirmed mechanism from a plausible explanation, and a blocked check from a failed product. Stop when the requested diagnosis or fix has sufficient evidence.
