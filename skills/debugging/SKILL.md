---
name: debugging
description: Diagnose failures, regressions, or performance problems whose cause is not yet established.
license: MIT
metadata:
  version: 1.1.2
  hosts: [codex, hermes-agent]
---

# Debugging

Start with the observed failure, expected behavior and affected scope. Reuse logs, traces, reproductions and baseline evidence. Preserve failing state when collecting evidence would destroy it. Diagnose or repair according to the user's request.

Distinguish product failure from a mistaken expectation, setup failure, environmental drift or an unrelated baseline problem. A file outside the diff can still be affected indirectly; an unavailable provider does not establish product behavior.

Form the smallest causal hypothesis that explains the observation and choose a result that would reject it. Inspect the decisive caller and state transition, including caches, serialization or asynchronous ordering when relevant. Run the cheapest useful discriminator. Retry only when new inputs, setup, hypotheses or independent observations could change the conclusion.

When different fixes leave the same failure unchanged, revisit their shared premise and the observation before adding another compensating fix. Inspect responsibility or workload distribution when it could explain the symptom.

Before authoring or changing a reproduction, diagnostic check, comparison script or inline probe, apply [Test Behavior](../test-behavior/SKILL.md). It decides check timing, independent expectations and lifetime, including explicitly requested regression or BRT delivery. Also apply it when an authorized repair removes or replaces a behavior contract, completes a migration or ends compatibility, even without a planned test edit. Continue causal diagnosis here; running an existing reproduction does not require a new test.

For performance, traces or version inconsistencies, use [runtime diagnosis](references/runtime.md). Add instrumentation only for a real evidence gap. When a repair is authorized, fix the responsible owner and verify affected behavior after the coherent change.

For authorized delegation or cross-context handoffs that need coordinated work boundaries, result integration or resource ownership, read [collaboration and state](../software-quality-workflows/references/collaboration-and-state.md).

Report the confirmed mechanism or remaining uncertainty, supporting observation and repair evidence. A blocked diagnostic path need not stop independent authorized work; name the missing fact without accumulating unchanged retries.
