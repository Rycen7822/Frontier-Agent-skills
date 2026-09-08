---
name: code-review
description: Review changes or review feedback for actionable defects and realistic impact.
license: MIT
metadata:
  version: 1.0.1
  hosts: [codex, hermes-agent]
---

# Code Review

Bind the requested change or design and intended behavior. Review-only requests do not authorize edits; when fixes are also requested, complete them within scope. Reuse valid context and findings, then inspect relevant owners and consumers.

Identify the critical premise that makes the change correct. Trace a realistic trigger through the implementation and affected consumers, including asynchronous state, serialization, generated surfaces or external behavior when relevant. Check surrounding contracts and tests before declaring a defect.

Prioritize concrete correctness, compatibility, data, security and operational failures. Explain the trigger, affected result and source location. Distinguish confirmed defects from uncertainty needing a small check. Preferences and hypothetical future requirements are not blocking findings.

Merge duplicate root causes. Accept, narrow or reject supplied review comments against current code and intent. Reviewer agreement is not evidence. After fixes, reassess affected findings and changed impact; reuse evidence whose relevant inputs remain valid.

Read [security boundaries](references/security.md) only for an implicated trust boundary. Use the [review contract](operator/review/result-consistency.md) or [publication contract](operator/review/publication-readiness.md) only for a consumer requiring those machine-readable records.

Return prioritized actionable findings, or state that none were found in the reviewed scope. Note material coverage limits. A review verdict does not establish unperformed tests or authority to merge.
