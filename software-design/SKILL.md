---
name: software-design
description: Resolve consequential requirements, ownership, API, data-model, or migration choices before implementation.
license: MIT
metadata:
  version: 1.1.0
  hosts: [codex, hermes-agent]
---

# Software Design

Resolve choices that materially affect the requested outcome. Read existing behavior, callers and constraints before asking the user for a consequential choice that available evidence cannot settle.

Model domain state and ownership before splitting files. Keep related representation and invariants together, make invalid states difficult to express, and expose a useful capability through a small interface. Prefer existing boundaries until concrete coupling or required change shows why they fail.

Compare the status quo and meaningful alternatives only when the decision needs them. Consider callers, failure semantics, compatibility and operations. Avoid speculative abstractions or manufactured design options. When retries or concurrency matter, identify state ownership, repeatable effects and partial failure. Validate data at the actual trust boundary.

Use a temporary prototype to resolve a specific uncertainty with a deciding observation. Distinguish measured behavior from production readiness. For a spatial decision, the [visual companion](operator/design-discovery/visual-runtime.md) is optional. Read [migration guidance](references/migration.md) for API or data transitions, or [security guidance](../code-review/references/security.md) for an implicated trust boundary.

State the chosen design, decisive reasons, affected owners and unresolved choices. Persist decisions when recovery or coordination needs them. For a design-only request, return the design; when implementation is requested, continue once the decisions are settled.
