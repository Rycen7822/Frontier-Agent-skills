# Plan State Contract

This reference is the single normative prose owner for durable `writing-plans` state. `schemas/plan-state.schema.json` owns field shapes and enums; this file owns semantics. Scripts may validate these contracts but must not invent design decisions or expand authority.

## Activation and format

- Brief normally creates no state. If a Brief state file appears, it must remain empty of graph/history content or fail `plan.profile-overbuilt`.
- Handoff may use state when source freshness, delegated slices, or resume matters.
- Program requires state.
- Canonical files are strict UTF-8 JSON with `schema_version: "1.1"`. YAML is intentionally unsupported by the stdlib-only implementation.
- Unknown fields, inputs over 2 MiB, nesting deeper than 40, and collections over 1,000 items are invalid.
- `execution_policy` is `standard` or `autonomous_closure`. Only a Program may use the closure policy; standard state must not carry `closure_contract_ref`.

## Identity and ownership

IDs are globally unique within one plan:

| Prefix | Object |
|---|---|
| `I-*` | global invariant |
| `F-*` | observed fact |
| `D-*` | design/plan decision |
| `E-*` | evidence claim or requirement |
| `P-*` | executable outcome node |
| `R-*` | risk and escalation rule |
| `G-*` | open gap or intentionally coarse fog |
| `X-*` | typed edge |
| `AP-*` | approval |
| `S-*` | source/snapshot binding |

Facts and decisions remain separate. A fact becoming stale can invalidate dependent decisions/nodes without pretending the original observation never existed. Plan state owns intended outcomes, invariants, decisions, coarse dependencies, required evidence, and fog. SQW workflow state owns actual runs, events, candidates, incumbents, locks, attempts, observed effects, and execution closure. This dual ledger boundary is mandatory; projected actual status never becomes a second execution truth.

Cross-artifact references use `<artifact-kind>:<artifact-id>#<local-id>`. Bare IDs are valid only within one plan.

## State semantics

Plan status:

```text
drafting | ready | active | blocked | completed | superseded
```

Node status:

```text
fog | ready | in_progress | blocked | done | failed |
invalidated | superseded | skipped
```

Evidence status:

```text
required | observed | stale | invalidated
```

`required` can be referenced but cannot satisfy completion. `fog` is intentional under-specification, not missing prose.

Core node transitions:

| From | To | Guard |
|---|---|---|
| `fog` | `ready` | objective, inputs, owner scope, side effects, and verifier are specific enough |
| `ready` | `in_progress` | dependencies complete, source/scope fresh, and approval present |
| `in_progress` | `done` | all required evidence is observed |
| `in_progress` | `failed` | structured failure is recorded by workflow state |
| `done` | `invalidated` | a source/fact/decision/evidence dependency changes |
| `failed` | `ready` | repair scope and bounded retry are approved |
| `blocked` | `ready` | blocker closes or is explicitly waived |
| any unfinished | `superseded` | replacement and lineage are explicit |

The plan validator checks current snapshots, not event history. Workflow state validates actual transitions.

## SQW workflow interop

An SQW workflow binds this plan through a minimal envelope: `plan_ref.artifact_ref`, `plan_ref.state_ref`, and the canonical plan `content_hash`. For `autonomous_closure`, the envelope also binds the loaded frozen `closure_contract_ref`: artifact, ID, epoch, canonical hash, source revision, scope hash, policy-bundle hash, authority hash, and ceiling must match. Workflow nodes use namespaced `plan:<plan-id>#P-*` / `#D-*` pointers instead of copying plan decisions or maintaining a second intended-outcome DAG. Execution discoveries emit `plan_change_proposed`; only the plan owner may issue a new canonical intended-state revision, while the SQW controller alone advances actual workflow state.

## Edges and effects

| Edge | Meaning |
|---|---|
| `control` | blocking execution/approval order |
| `data` | output is a structured input |
| `evidence` | a claim/decision/node relies on evidence |
| `invariant` | a node must preserve a global invariant |
| `effect` | a node changes a state class used by rollback/retry |
| `resource` | nodes share a lock or mutable resource |
| `approval` | an operation requires explicit authority |

`depends_on` and `control` edges both participate in cycle/frontier checks. Edge `sensitivity.fields` limits invalidation to semantic fields; formatting-only changes must not invalidate a consumer that depends only on an exit code or stable claim.

`read_set`/`write_set`/`resource_set` are conservative effect declarations. Glob overlap is treated as conflict when safety cannot be proven. External non-idempotent or destructive nodes require a granted approval edge and may not retry without an idempotency key or manual reconciliation.

## Proof-first nodes

Every executable node defines:

- one observable objective and completion criterion;
- explicit inputs/outputs and dependencies;
- allowed reads/writes/resources and side-effect level;
- verifier kind, required evidence, before/after distinction when applicable, and false-green risk;
- bounded retry policy;
- `constraint_refs`, `corner_refs`, and `verifier_requirement_refs` resolved against the loaded frozen contract when the closure policy is active;
- refinement lineage.

A command string alone is not proof. A done node's required evidence must be `observed`, source-bound where applicable, and still fresh.

## Source, scope, snapshots, and hashing

- `source.base_revision`, `source.scope_hash`, and `source.observed_at` bind the plan to inspected reality.
- `source.policy_bundle_hash` binds the policy used to compile the plan. A closure plan additionally binds the frozen contract's source, scope, policy, authority, ID, epoch, and canonical hash; its actual plan scope may narrow but never widen the contract scope.
- `scope.allowed_writes` is the authorization ceiling; node writes outside it fail validation.
- Line/snippet/symbol/capsule snapshots require `source_revision`; content-bound snapshots require a SHA-256.
- A symbol snapshot also records `symbol`; freshness binds the snapshot path plus the terminal identity token and reports a missing/renamed token without invalidating unrelated branches.
- A done command verifier uses a structured `namespace:target` reference. `path`/`script`/`schema` targets and path-shaped test targets must still exist; `command` targets must resolve without executing them; project-defined `pytest`/`test` aliases remain opaque but non-empty.
- External evidence may bind both `max_age_hours` and `expected_version`; freshness compares `observed_at` and `external_version` with that caller policy.
- Canonical state hashes use compact sorted-key JSON with `content_hash` omitted before hashing, then prefix the digest with `sha256:`. A capsule source hash additionally excludes generated capsule snapshot records, so recording the generated artifact cannot create a self-referential hash.
- Freshness is `fresh`, `partially_stale`, or `stale`. Partial staleness names affected IDs; it never silently invalidates the whole plan or silently preserves affected nodes.
- `check_plan_freshness.py --changed-ref ID --changed-field ID=FIELD` accepts repeatable caller observations. A field-sensitive edge is traversed only when the declared field intersects `edge.sensitivity.fields`; undeclared field detail propagates conservatively.
- `explicit-unversioned` is permitted only when no repository revision exists; source/scope limitations remain visible.

## Context capsules

Capsules are generated projections, not a second truth. Mandatory fields are goal, node objective/completion criterion, global invariants, source/scope/state hashes, closure contract identity when bound, node constraint/corner/verifier-requirement refs, relevant decisions, authority/protected boundaries, allowed reads/writes/resources, side effects/approval, verifier, false-green risk, and blocking gaps. An optional SQW runtime projection is limited to incumbent identity, hard failures, and budget state. Optional fact/evidence summaries are included by relevance until the budget is reached.

Never project a full contract, candidate history, full workflow history, all future nodes, chat transcripts, raw logs, unrelated decisions, raw sensitive values, or arbitrary source excerpts. Sensitive objects appear only as redacted IDs. If optional objects are omitted, return their IDs and `requires_on_demand_read: true`; never silently truncate mandatory safety fields.

Credential-shaped values must be replaced by controlled pointers and marked `sensitive`. `plan.sensitive-unclassified` rejects an unclassified raw value; the capsule renderer also applies pattern-based redaction as defense in depth.

## Closure

Plan closure records intended-artifact readiness, never actual implementation acceptance. For `autonomous_closure`, writing is complete only when the frozen contract identity is valid, canonical plan state validates against it, required intended-state gaps are resolved, and the SQW handoff is emitted. Actual evidence, sign-off, terminal status, publication, and workflow closure remain SQW state even if the plan projects their stable IDs.

Use both:

```text
closure.status: open | complete | incomplete | inconclusive
closure.epistemic_status: needs_repair | verified_within_scope |
  blocked | empirical_validation_required
```

## Deterministic violations

The validator emits JSON Pointer paths and stable codes:

```text
plan.schema
plan.contract-forbidden
plan.contract-profile
plan.contract-missing
plan.contract-invalid
plan.contract-stale
plan.contract-source-mismatch
plan.contract-plan-hash
plan.contract-scope-mismatch
plan.contract-epoch-required
plan.node-contract-ref
plan.candidate-id
plan.default-unsafe
plan.id-duplicate
plan.ref-missing
plan.control-cycle
plan.frontier-stale
plan.done-without-evidence
plan.scope-write
plan.source-stale
plan.snapshot-unbound
plan.retry-unsafe
plan.approval-missing
plan.effect-conflict
plan.invariant-unbound
plan.fog-executed
plan.invalidated-dependent-live
plan.closure-premature
plan.profile-overbuilt
plan.owner-duplicate
plan.sensitive-unclassified
plan.verifier-unresolved
plan.evidence-unbound
```

Schema validity is not semantic correctness. Model/human review still owns design quality; real evidence still owns completion.

## One-time 1.0 to 1.1 migration

`scripts/migrate_plan_state.py` accepts only schema 1.0 input and produces a separate no-overwrite 1.1 state plus migration report. It never fabricates a Closure Contract or upgrades a legacy plan into `autonomous_closure`.

- Existing IDs and state meaning are preserved.
- The caller supplies the current policy-bundle hash; migration defaults Execution policy to `standard` and adds empty node contract-reference arrays.
- Decision provenance is derived only from explicit repository or design-audit evidence. Materiality, reversibility, contract effect, or provenance that cannot be proven is emitted as a structured unresolved row rather than invented.
- The report binds source and output state hashes. Each artifact uses atomic no-overwrite publication; if report publication loses a race, the already published state is rolled back so no split pair remains.
- Symlink, malformed, oversized, non-finite, wrong-version, or existing-output inputs fail closed.
