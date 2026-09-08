---
name: software-design
description: "Resolve substantive choices in requirements, data models, module boundaries, APIs, or migrations. Use when the design is unsettled; settled implementation belongs to normal development and execution planning."
license: MIT
metadata:
  version: 1.0.0
  hosts: [codex, hermes-agent]
---

# Software Design

Resolve the choices that materially affect the requested outcome. Read existing behavior, callers and constraints before asking questions. Retrieve missing facts directly; ask the user only for a consequential product choice that available evidence cannot settle. Clear requirements do not need a new specification ritual.

Model the domain and ownership before splitting files or functions. Put related representation and invariants together, make invalid states difficult to express, and expose a useful capability through a small interface. A module can hide substantial complexity without creating a deep call chain. Prefer existing boundaries until concrete coupling, repeated decisions or required change shows why they fail.

Consider the status quo and genuinely different alternatives only when the decision needs them. Compare effects on callers, state, failure semantics, compatibility and operations. Do not manufacture multiple designs, prototypes or reviewers for an obvious local choice. Avoid hypothetical abstractions, configuration and compatibility layers.

Make retry and concurrency behavior explicit when implicated: who owns the state, what can repeat, where partial failure is visible, and whether an operation is idempotent. Separate independent state before adding coordination. Validate data at real trust boundaries; internal origin alone does not guarantee validity.

Use a temporary prototype only to answer a concrete uncertainty. Choose a deciding observation and stop when it is answered; keep experimental state isolated and distinguish measured behavior from production readiness. For an inherently spatial decision needing a local interactive comparison, the existing [visual companion](operator/design-discovery/visual-runtime.md) is optional.

For API or data migration, read [compatibility and migration](references/migration.md). For an implicated security boundary, consult the precise [security guidance](../code-review/references/security.md) without loading a second workflow.

State the chosen design, decisive reasons, affected owners and any unresolved choice. Persist a specification only when the task needs durable decisions. A design-only request does not authorize implementation; when implementation is requested, continue once decisions are settled. Use an execution plan only when the remaining work benefits from one.
