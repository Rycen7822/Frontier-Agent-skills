<!-- Generated catalog: schemas/plan-state.schema.json + validate_plan_state.py + tests/fixtures/plan-state/invalid-cases.json. -->
# Plan-state diagnostics

Stable semantic codes are:

- `plan.schema`, `plan.id-duplicate`, `plan.ref-missing`, `plan.control-cycle`, `plan.frontier-stale`
- `plan.done-without-evidence`, `plan.scope-write`, `plan.source-stale`, `plan.snapshot-unbound`
- `plan.retry-unsafe`, `plan.approval-missing`, `plan.effect-conflict`, `plan.invariant-unbound`
- `plan.fog-executed`, `plan.invalidated-dependent-live`, `plan.completion-premature`
- `plan.owner-duplicate`, `plan.sensitive-unclassified`, `plan.verifier-unresolved`, `plan.evidence-unbound`
- `plan.queue-duplicate`, `plan.queue-terminal`, `plan.queue-status`, `plan.queue-subject`
- `plan.source-binding`, `plan.transition-scope`, `plan.transition-init`, `plan.transition-card`
- `plan.artifact-duplicate`, `plan.artifact-scope`, `plan.inline-render-budget`

Card-cycle runtime errors are `E_COMMAND_SCHEMA`, `E_COMMAND_BUDGET`, `E_CONTRACT_INVALID`, `E_ROOT_ROLE`, `E_ORPHAN_CONFLICT`, `E_STATE_STALE`, `E_STATE_ADVANCED`, `E_STATE_BUDGET`, `E_SOURCE_REVISION_CHANGED`, `E_PROJECTION_BUDGET`, `E_CONTEXT_NOT_CURRENT`, and `E_HANDOFF_INVALID`. Errors never authorize fallback writes, profile switching, truncation, queue edits, or cleanup of foreign bytes.
