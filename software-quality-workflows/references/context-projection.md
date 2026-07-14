# Workflow Context Projection

`scripts/project_context.py` renders a bounded view of canonical workflow state. The projection is disposable and must include `workflow_id`, `state_version`, source/scope identity, authority ceiling, global invariants, current frontier, node effects, verifier requirements, retry/approval state, and relevant failure/evidence pointers.

## Inclusion order

1. Mandatory safety identity, authority, invariants, and frontier objectives.
2. Blocking inputs, fresh evidence summaries, verifier claims, and active locks.
3. Most recent relevant failure and explicit out-of-scope/protected paths.
4. Optional recent events or non-blocking evidence until the budget is reached.

When over budget, remove history first and optional non-blocking references second. Never truncate authority, invariants, objective, side effects, approvals, proof requirements, or state version. Return omitted IDs and `requires_on_demand_read` instead of silently dropping them.

Sensitive objects render only ID, classification, and controlled pointer. Credential-shaped values receive defense-in-depth redaction even if classification was missed; the validator still reports the underlying state defect.

The controller must compare the projection's `state_version` before committing a result. A stale capsule is not authority to update canonical state.
