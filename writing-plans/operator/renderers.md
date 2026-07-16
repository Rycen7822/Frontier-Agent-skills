# Renderer operations

Renderers are read-only projections of canonical plan state. They must not mutate the plan, infer execution success, or become a second policy owner.

## Profile renderer

`render_plan_profile.py` emits one requested profile:

- Brief: goal, scope, acceptance, blockers, and immediate proof.
- Handoff: ordered outcome slices, current frontier, boundaries, and verification commands for standard execution.
- Program: only the current frontier, decisions and invariants that bind it, canonical artifact pointers, and the expand-migrate-contract state transition.

Program output has an 8,192-byte hard ceiling. The renderer fails closed if mandatory content exceeds it; it never truncates a required decision, invariant, source identity, or frontier field. Historical and unrelated future nodes remain in canonical state and are retrieved on demand.

## Context capsule renderer

`render_context_capsule.py` projects one node. Mandatory content is:

- goal and node completion criterion;
- bundle, policy-bundle, reference-manifest, source, scope, state version, and state hash;
- exact card IDs/hashes and projection spec ID/hash;
- applicable invariants, constraints, corners, decisions, blockers, authority, and protected boundaries;
- reads, writes, resources, effects, approvals, verifier, false-green risk, and qualifying evidence needs;
- frozen Closure Contract identity and bounded runtime facts when autonomous closure is active.

The effective output ceiling is 8,192 bytes even if a caller asks for more. Optional facts and evidence are admitted by relevance only after mandatory content. If mandatory content exceeds the ceiling, rendering raises `mandatory capsule exceeds budget`; mandatory content is never truncated. Metadata reports mandatory bytes/chars and must report zero mandatory truncations.

## Rebuild and verification

Treat generated profiles and capsules as caches:

1. validate canonical state;
2. render from the current state hash and exact card identities;
3. store the returned projection identity in the capsule snapshot;
4. run freshness checking before reuse;
5. delete and regenerate on state, projection, manifest, or referenced-card drift.

A rebuild must be deterministic for identical canonical inputs. Deleting all generated projections must not change state hash, graph frontier, evidence, decisions, or workflow-controller state.
