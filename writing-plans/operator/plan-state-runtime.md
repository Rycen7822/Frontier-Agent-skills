# Plan-state runtime contract

This document is operator detail for the canonical machine-readable plan state. It is not a reference card and must not appear in `reference-cards.manifest.json`.

## Authority and identity

- `schemas/plan-state.schema.json` owns the serialized shape. `validate_plan_state.py` owns cross-field semantics.
- The state describes planning truth, not actual implementation, publication, or workflow completion.
- `source.bundle_id`, `source.policy_bundle_hash`, and `source.reference_manifest_hash` bind the plan to its executable policy and card graph.
- `policy_claims` contain exactly `policy_id`, `bundle_version`, and `policy_hash`. A Markdown path is never policy identity.
- `content_hash` is the canonical state hash with the derived hash field excluded. Any semantic change increments `state_version` and recomputes the hash.

Plan statuses are `drafting`, `ready`, `active`, `blocked`, `completed`, and `superseded`. Node statuses are `fog`, `ready`, `in_progress`, `blocked`, `done`, `failed`, `invalidated`, `superseded`, and `skipped`.

## Graph and frontier

Nodes are outcome slices. Each node declares inputs, outputs, `read_set`, `write_set`, `resource_set`, `effect_set`, applicable constraint/corner/verifier references, approval state, and a completion oracle. Edges are typed as `control`, `data`, `evidence`, `invariant`, `effect`, `resource`, or `approval` and may declare field sensitivity.

The stored frontier is an assertion checked against graph readiness; it is never trusted merely because the schema accepts it. A ready node has satisfied control dependencies, available required inputs, no unresolved blocker, all necessary approval, and no applicable invariant or resource/effect conflict. Hidden shared state, root assumptions, source/scope drift, or global invariant drift require parent/global replanning rather than local repair.

Invariants declare:

- `locality`: `global`, `subgraph`, or `node`;
- `applicability`: the condition under which the invariant binds;
- `targets`: explicit node IDs for non-global locality.

A high-risk node must have at least one applicable invariant. Read/write, write/read, write/write, shared-resource, and declared-effect conflicts are blocking even if dependency edges do not expose them.

## Evidence and completion

`done` requires qualifying evidence bound to the node verifier and current source identity. Observed evidence records a usable freshness policy; command, schema, symbol, artifact, and external-version bindings are resolved rather than accepted as prose. A failed or invalidated prerequisite cannot leave a dependent live. Plan-level completion requires every required node terminal, no stale source binding, and no unresolved blocking evidence or approval.

For autonomous closure, the plan binds a frozen Closure Contract by ID, epoch, content hash, source revision, scope, policy bundle, reference-card manifest, and authority boundary. Contract or policy-root drift invalidates the whole plan. The contract remains upstream of the plan and cannot refer to a future plan or candidate.

## Freshness and invalidation

`check_plan_freshness.py` classifies drift by ownership:

- source revision, scope, bundle, policy bundle, frozen contract, global invariant, or root assumption drift is global;
- typed node/input/evidence changes propagate only across relevant graph edges and declared field sensitivity;
- reference-manifest or card-hash drift invalidates generated context capsules only;
- capsule/state-version drift invalidates that projection, not canonical plan truth.

Reports name directly stale IDs, affected IDs, preserved IDs, repair type, and escalation reasons. Unknown field sensitivity propagates conservatively. A local invalidation must not silently widen to unrelated branches.

## Generated snapshots

Capsules are disposable projections. Their snapshot records the canonical `plan_state_hash` and `plan_state_version`, exact `card_refs` with card hashes, and the projection spec ID/hash. Deleting and rebuilding every capsule must leave canonical plan state unchanged.

Never edit a capsule back into canonical state. Re-observe the repository or edit the plan state, validate it, then regenerate the projection.

## Event boundary

Runtime commands emit a state transition only when canonical state changes. An event records the prior and next state identities plus the typed reason. Schema-valid no-op events are forbidden. Planning events do not claim execution success; execution consumes `schemas/plan-execution-handoff.schema.json` and reports through the software-quality workflow controller.
