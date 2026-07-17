<!-- Generated catalog: schemas/plan-state.schema.json + validate_plan_state.py + tests/fixtures/plan-state/invalid-cases.json. -->
# Plan-state diagnostics

The JSON diagnostic `code` is stable automation identity. Human messages may improve without changing the code. `path` locates the failing field and `object_id` identifies a stable graph object when available.

Every stable semantic code has a negative fixture:

- `plan.schema` — serialized input violates the schema.
- `plan.id-duplicate` — a stable object ID is reused.
- `plan.ref-missing` — a typed reference does not resolve.
- `plan.control-cycle` — control dependencies contain a cycle.
- `plan.frontier-stale` — stored frontier differs from computed readiness.
- `plan.done-without-evidence` — a done node lacks qualifying proof.
- `plan.scope-write` — a node writes outside admitted scope.
- `plan.source-stale` — canonical source identity is stale.
- `plan.snapshot-unbound` — a snapshot lacks a resolvable source binding.
- `plan.retry-unsafe` — retry semantics can repeat an unsafe side effect.
- `plan.approval-missing` — execution would exceed admitted approval.
- `plan.effect-conflict` — concurrent node effects conflict.
- `plan.invariant-unbound` — a required invariant is not applicable to its target.
- `plan.fog-executed` — unresolved fog was treated as executable.
- `plan.invalidated-dependent-live` — a dependent remains live after prerequisite invalidation.
- `plan.completion-premature` — plan completion is asserted before required evidence, blockers, and nodes are resolved.
- `plan.profile-overbuilt` — a bounded profile includes disallowed state.
- `plan.owner-duplicate` — one policy has multiple normative owners.
- `plan.sensitive-unclassified` — sensitive context lacks classification.
- `plan.verifier-unresolved` — a verifier target cannot be resolved.
- `plan.evidence-unbound` — evidence is not bound to source, verifier, or node identity.

Additional runtime codes may be emitted by their owning validators. Do not add a stable `plan.*` code without a negative fixture and this generated-catalog parity check.
