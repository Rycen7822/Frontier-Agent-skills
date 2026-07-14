---
name: writing-plans
description: Use when an authorized software change needs a durable implementation plan, a cross-context handoff, or an autonomous-closure request must be compiled into a frozen intended-state contract. Do not use for routine Direct edits, unresolved diagnosis, or actual execution, verification, sign-off, publication, or workflow closure.
version: 3.0.0
author: Hermes Agent (adapted from obra/superpowers)
license: MIT
metadata:
  hermes:
    tags: [planning, design, implementation, closure-contract, documentation]
    category: software-development
    related_skills: [software-quality-workflows]
---

# Writing Plans

## Owner contract

Own the intended-state artifacts for a software change: the lightest durable plan that preserves scope, constraints, decisions, dependency order, recovery, and proof, plus a frozen Closure Contract when autonomous closure is eligible. Compile what must become true; do not claim what has actually become true.

`writing-plans` does not diagnose an unknown failure, edit production code, run candidate search, accept verifier evidence, advance workflow state, sign off, publish, or close a task. Execution is owned by `software-quality-workflows` (SQW) and its domain owners. Do not duplicate the execution lifecycle, cleanup policy, verification authority, or version-control policy in a plan. Direct work remains planless unless the user explicitly requests a durable plan.

A plan is an index over authoritative sources and stable contracts, not a copy of the source tree. Prefer IDs, symbols, schemas, invariants, acceptance examples, and source-bound pointers over speculative code or fragile line numbers.

## Route before planning

Create a bounded JSON facts object and run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/assess_plan_mode.py facts.json
```

Honor the returned route and `execution_policy`; do not reimplement its precedence in prose:

1. Missing authority or a typed admission failure stops planning at the reported terminal handoff.
2. Unknown root cause routes to SQW diagnosis before implementation planning.
3. Underdefined outcome routes to intent and design discovery.
4. Long non-software drafting routes to the long-document owner; a disposable feasibility question routes to the spike contract.
5. A clear, local, reversible same-session change routes to SQW Direct unless a plan was explicitly requested.
6. An autonomous request uses the three-state closure admission result below.
7. Otherwise select the lightest standard profile that preserves the required handoff and recovery evidence.

Nullable safety facts are unknown, not false. A public contract, migration, external-system dependency, long corpus, or spike condition that is not established must fail closed. Strategy families and independent write slices are separate facts.

## Autonomous closure branch

Closure admission has exactly three outcomes:

- `eligible`: compile and freeze a Closure Contract, then build a contract-bound Program plan.
- `ineligible`: fall back to the returned Direct or standard planning route without creating a closure contract.
- typed terminal: emit the bounded compiler/admission handoff named by the route; do not invent intent and do not pause an autonomous workflow waiting for a routine preference.

Before freeze, a bounded spike may resolve one explicitly identified feasibility uncertainty. Its evidence can inform the contract, but spike code and candidate history never become the contract or production implementation by silent promotion.

The Closure Contract is distinct from the plan. It fixes admitted intent, authority, hard constraints, ordered soft objectives, corners, verifier requirements, and search/publication policy. The Program plan describes intended implementation structure under that frozen contract. Neither artifact records actual execution state.

## Select Brief / Handoff / Program/Migration Map

| Profile | Execution policy | Use | Durable shape |
|---|---|---|---|
| **Brief Change Card** | `standard` | Small, clear, same-session change where a compact plan was requested | One bounded Markdown card; no graph and no closure contract |
| **Executable Handoff** | `standard` | Another context or agent must resume, or ordering/recovery evidence matters | Markdown handoff with anchors, ordered slices, proof, rollback, and unresolved gaps |
| **Program/Migration Map** | `standard` or `autonomous_closure` | Multi-owner graph, migration, public contract, or eligible closure | Canonical plan-state 1.1 plus rendered map and context capsules |

Direct is an SQW execution route, not a fourth plan profile. Autonomous closure is Program-only. If the selected profile cannot preserve a public migration, authority boundary, cross-context recovery, or verifier dependency, move upward rather than compressing away the constraint.

## Compile and freeze contract

For `autonomous_closure`, compile a draft against `schemas/closure-contract.schema.json` and the semantic owner in `scripts/validate_closure_contract.py`. The draft must bind an admitted request, externally observed source revision, scope hash, policy-bundle hash, authority hash and ceiling, hard/soft/corner IDs, verifier/oracle requirements, protected paths, and fixed terminal vocabulary.

Validate before freeze:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_closure_contract.py draft.json --schema schemas/closure-contract.schema.json --for-freeze
```

Freeze to a separate, new path with `scripts/freeze_closure_contract.py`, supplying the independently observed revision, scope, policy, and authority bindings. Freeze is atomic and no-overwrite; never edit a frozen epoch. The contract must not contain a plan reference, candidate, incumbent, runtime verdict, raw log, or publication claim.

If authoritative sources conflict, hard constraints are unsatisfiable, or required intent cannot be inferred safely, produce the minimal typed ambiguity/unsat compiler handoff. Do not soften a hard constraint, widen authority, or fabricate a default merely to obtain a valid file.

## Build the canonical plan

Program state uses `schemas/plan-state.schema.json` version 1.1. A contract-bound Program records `execution_policy: autonomous_closure`, the exact `closure_contract_ref`, source/policy hashes, decision provenance/materiality/reversibility/contract effect, and node-level constraint, corner, and verifier-requirement references. Standard plans must not carry a closure contract.

Validate the canonical state before rendering:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_plan_state.py standard-plan-state.json
PYTHONDONTWRITEBYTECODE=1 python3 scripts/validate_plan_state.py closure-plan-state.json --closure-contract frozen-contract.json
```

Use `scripts/render_plan_profile.py` for Brief, Handoff, or Program output and `scripts/render_context_capsule.py` for a bounded node handoff. Derive rendered coverage from canonical state; do not accept caller-authored summaries as substitutes for plan identity or constraint bindings.

Each node names one stable owner seam, inputs/preconditions, intended outputs, dependencies, invariants, acceptance proof, false-green risks, rollback/recovery, and blocking gaps. Keep a dual ledger: intended plan state here, actual execution/evidence state in SQW. Candidate IDs may appear only as bounded SQW evidence references, never as canonical plan nodes or completion claims.

## Progressive disclosure

Keep the entry point compact and load references only for the active profile or risk. The default active-reference budget is five. Exceed it only when the route returns an explicit reason for a public contract, migration, external system, long corpus, or spike, and record that reason in the handoff.

Context capsules carry the frozen contract identity, current canonical node, required invariants/decisions/authority, false-green risks, blocking gaps, and a bounded runtime projection. Exclude full contracts, candidate histories, raw logs, generated corpora, and repeated source prose. Re-open source anchors at execution time instead of treating an old capsule as current truth.

## Handoff to SQW

Hand off exact artifact paths and identities:

- selected profile and `execution_policy`;
- validated canonical plan-state path/hash and current node/frontier;
- frozen contract path/hash/ID/epoch for autonomous closure;
- source revision, scope hash, policy-bundle hash, authority ceiling, protected paths, and unresolved certificates;
- required verifier, rollback, migration, and publication boundaries.

SQW owns admission into execution, controller transitions, isolated candidate work, verifier qualification, actual-state/evidence ledgers, independent review, sign-off, terminal state, and publication. A writing handoff requests those owners; it never impersonates them.

## Completion

For a standard profile, completion means the requested plan artifact is internally consistent, source-bound, validated where a schema exists, and handed off with explicit gaps. For autonomous closure, writing completion is exactly `contract_frozen + plan_validated + handoff_emitted`.

Writing completion does not mean implementation, sign-off, publication, or workflow closure. Report those as unproven until SQW supplies fresh evidence through its owning workflow.

The actual-state handoff may report `needs_repair`, `verified_within_scope`, `blocked`, or `empirical_validation_required`. These are SQW-owned epistemic statuses, not plan completion claims.

## Reference map

- [Architecture decision records](references/architecture-decision-records.md)
- [Closure Contract](references/closure-contract.md)
- [Context and output economy](references/context-and-output-economy-plans.md)
- [Deprecation and migration plans](references/deprecation-migration-plans.md)
- [Design-audit compression ledger](references/design-audit-compression-ledger.md)
- [Implementation slicing and context capsules](references/implementation-slicing-and-context-capsules.md)
- [Plan profiles](references/plan-profiles.md)
- [Plan-state contract](references/plan-state-contract.md)
- [Disposable feasibility spikes](references/spike.md)
