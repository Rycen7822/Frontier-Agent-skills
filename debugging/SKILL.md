---
name: debugging
description: Diagnose failures, regressions, or performance problems whose cause is not yet established.
license: MIT
metadata:
  version: 1.1.0
  hosts: [codex, hermes-agent]
---

# Debugging

Start with the observed failure, expected behavior and affected scope. Reuse logs, traces, reproductions and baseline evidence. Preserve failing state when collecting evidence would destroy it. Diagnose or repair according to the user's request.

Distinguish product failure from a mistaken expectation, setup failure, environmental drift or an unrelated baseline problem. A file outside the diff can still be affected indirectly; an unavailable provider does not establish product behavior.

Form the smallest causal hypothesis that explains the observation and choose a result that would reject it. Inspect the decisive caller and state transition, including caches, serialization or asynchronous ordering when relevant. Run the cheapest useful discriminator. Retry only when new inputs, setup, hypotheses or independent observations could change the conclusion.

For performance, traces or version inconsistencies, use [runtime diagnosis](references/runtime.md). Add instrumentation only for a real evidence gap. When a repair is authorized, fix the responsible owner and verify affected behavior after the coherent change. Reuse valid checks; add a regression test only for meaningful recurrence risk, and keep one-off probes temporary.

Report the confirmed mechanism or remaining uncertainty, supporting observation and repair evidence. A blocked diagnostic path need not stop independent authorized work; name the missing fact without accumulating unchanged retries.
