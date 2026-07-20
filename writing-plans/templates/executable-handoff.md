# Typed Executable Handoff v3: {{ goal }}

- Handoff ID: `wp-handoff:{{ canonical payload sha256 }}`
- Producer: `{{ profile }} / {{ card_id }} / {{ completion_id }}`
- Plan/state binding: `{{ plan_id or standalone }} / {{ state_hash or null }}`
- Source identity: `{{ kind }} / {{ identity_hash }}`
- Planning scope binding: `{{ binding_id }}`
- Bundle: `frontier-engineering/6.0.0+5.0.0`

This artifact records execution-authority requirements. It does not grant or claim actual authority. The receiver must route through Software Quality Workflows and re-establish scope and effect authority.

## Typed payload

- Goal/non-goals: observable destination and explicit exclusions.
- Global invariants: ordered `{ref, statement}` entries.
- Owner seams: ordered `{owner, paths, resources, effects}` entries.
- Requirements: exact fact, decision, evidence, approval, and policy completion refs.
- Ordered slices: `{slice_id,node_ref,objective,depends_on,read_set,write_set,effect_set,completion_criterion}`.
- Rollback: typed strategy, ordered steps, verifier refs.
- Target entry: `software-quality-workflows`, `route_phase=entry`, required SQW decision IDs.
- Unresolved blockers: facts the receiver must not invent.

No filesystem state path, free output path, inferred authority, or unbound artifact-type reference is part of this contract.
