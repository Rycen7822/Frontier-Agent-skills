---
name: code-review
description: "Review a diff, assess change impact, challenge a proposed design, or validate review feedback. Find actionable defects with concrete triggers and evidence; review alone does not authorize edits."
license: MIT
metadata:
  version: 1.0.0
  hosts: [codex, hermes-agent]
---

# Code Review

Bind the requested change or design and the intended behavior. Review is read-only unless fixes are requested. Reuse valid context and prior findings; inspect changes and relevant owners or consumers without launching a repository-wide audit.

Find the critical premise that makes the change correct. Trace its realistic trigger through the changed implementation and affected consumers, including serialization, callbacks, asynchronous state, generated surfaces or third-party behavior where relevant. Check the surrounding contract and existing tests before declaring a defect.

Prioritize concrete correctness, compatibility, data, security and operational failures. Explain the triggering conditions, affected result and source location. Distinguish confirmed defects from uncertainty requiring a small check. Preferences, hypothetical future requirements and alternative formatting are not blocking findings.

Merge duplicate root causes. Reassess supplied review comments against current code and intent: accept, narrow or reject them on substance. Neither reviewer count nor model agreement substitutes for evidence. Use additional review only when an independent perspective can resolve a material uncertainty and delegation is authorized.

Use [security boundaries](references/security.md) only for an implicated trust boundary. When an existing consumer requires machine-readable review or publication records, use the corresponding [review contract](operator/review/result-consistency.md) or [publication contract](operator/review/publication-readiness.md); ordinary reviews need neither artifact.

Reuse evidence while the relevant behavior, dependency and environment remain unchanged. A new commit alone does not invalidate a finding or check; an unchanged patch alone does not prove freshness. After fixes, reassess the affected finding and any changed impact, not every unrelated review path.

Return a short prioritized set of actionable findings, or say no actionable issue was found within the reviewed scope. State material coverage limits. A review verdict is not test execution, publication readiness or authority to merge. Stop when the scoped judgment is supported.
