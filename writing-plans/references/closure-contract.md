# Closure Contract

The Closure Contract is the frozen intended-state specification for an admitted autonomous-closure request. This document owns its compilation rules; SQW owns execution, evidence, state transitions, terminal verdicts, and publication.

## Ownership and activation

Create a contract only when `scripts/assess_plan_mode.py` returns `closure_eligibility: eligible` with `execution_policy: autonomous_closure`. Direct, standard-plan, ineligible, and typed-terminal routes do not create a contract. The contract is neither a plan nor a workflow-state record.

## Source hierarchy and intent inference

Resolve intent in this order: explicit authorized user requirements; controlling repository and workspace policy; admitted external/public contracts; current source, tests, schemas, and runtime facts; then conservative inference. Record each material source with an externally observed revision or stable anchor and provenance. Use `design-audit-compression-ledger.md` for competing design evidence and `intent-and-design-discovery.md` when the outcome remains underdefined.

## Authority and autonomy ceiling

Bind the admitted request, read/write scope, protected paths, preauthorized and forbidden operations, external-system limits, sandbox/network/VCS/publication limits, authority hash, and authority ceiling. The contract may narrow but never widen authority. SQW's `authority-and-scope.md` remains authoritative for runtime enforcement.

## Assumptions and safe defaults

Every assumption records provenance, confidence, reversibility, affected constraints, and a validation or rollback trigger. A safe default must be local, reversible, non-public, non-destructive, and inside the admitted authority ceiling. Unknown nullable risk facts fail closed. Never default credentials, destructive cleanup, public migration, external side effects, or publication.

## Hard constraints

Give each hard constraint a stable ID, authoritative source anchor, statement, affected scope, required corner coverage, and verifier-requirement references. Hard constraints cannot be traded against soft objectives or silently softened. Conflicts produce a certificate rather than a weakened contract. Migration removal conditions also follow `deprecation-migration-plans.md`.

## Soft objectives and lexicographic order

Give each soft objective a stable ID and explicit priority. Comparison is lexicographic after all hard constraints pass; weighted averages may not hide a hard failure or reverse a higher-priority objective. Tie-breakers must be deterministic and source-bound.

## Corner selection

Enumerate required semantic corners with stable IDs, selection rationale, related hard constraints, fixtures/oracles, and minimum coverage. Include boundary, failure, migration, compatibility, and authority corners where applicable. Do not infer closure from a happy path alone.

## Verifier requirements

Each requirement identifies its oracle class, qualification level, evidence shape, independence needs, protected-kernel dependencies, and false-green risks. Contract compilation describes required proof; SQW's `verifier-kernel.md` qualifies and runs the verifier. Candidate-supplied tests are supplementary and cannot replace protected oracles.

## Search and publication policy

Fix permitted strategy families, candidate/time/resource budgets, stop rules, deterministic comparison order, and incumbent retention. Search remains subordinate to hard constraints and authority. Candidate state, portfolios, raw logs, and actual verdicts stay in SQW. Publication is a separate authorized transition and is never implied by acceptance. A feasibility uncertainty may use `spike.md`, but spike code cannot enter production by silent promotion.

## Ambiguity / unsat certificates

When required intent is not safely inferable, emit the smallest source-bound `SPEC_UNDERDETERMINED` compiler certificate naming the missing decision and why defaults are unsafe. When hard requirements conflict, emit `SPEC_UNSAT` with the minimal conflicting set. These are inputs to SQW's controller; writing does not claim the workflow terminal state.

The frozen vocabulary is exactly `CLOSED`, `SPEC_UNDERDETERMINED`, `SPEC_UNSAT`, `AUTHORITY_BLOCKED`, `ENVIRONMENT_UNAVAILABLE`, `BASELINE_UNSTABLE`, `VERIFIER_UNQUALIFIED`, `NON_CONVERGED`, `BUDGET_EXHAUSTED`, `WORKFLOW_INVALID`, and `ABORTED_BY_SOURCE_DRIFT`. The contract permits these values; only the SQW controller may commit one as actual terminal state.

## Freeze, epoch, supersession

Freeze only after schema and semantic validation bind the externally observed source revision, scope hash, policy-bundle hash, authority hash/ceiling, and canonical self-excluding contract hash. Publish atomically to a new no-overwrite path and make the visible artifact read-only. A frozen contract must not contain a plan reference. Material source, policy, authority, scope, intent, constraint, corner, or verifier change requires a new epoch; supersession never mutates the old epoch.

## Handoff to SQW

Hand off contract path/hash/ID/epoch, admitted request and source bindings, authority ceiling, protected paths, hard/soft/corner/verifier IDs, search and publication policy, and any compiler certificate. The Program plan binds it through `plan-state-contract.md`. SQW's `autonomous-closure.md` owns admission, controller-only transitions, candidates, actual evidence, sign-off, terminal state, and publication.

## Completion criterion

This owner is complete only when the contract is valid, frozen at a new immutable path, independently bound to its external identities, and handed to a validated Program plan and SQW. Its local completion expression is `contract_frozen + plan_validated + handoff_emitted`; it is not implementation or workflow closure.
