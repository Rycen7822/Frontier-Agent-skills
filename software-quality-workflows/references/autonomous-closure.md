# Autonomous Software Design Closure

> Owner: autonomous-closure
> Authority: normative_owner
> Role: lifecycle
> Phases: ADMISSION, SPEC_COMPILING, CONTRACT_FROZEN, BASELINING, VERIFIER_QUALIFYING, PLANNING, SEARCHING, SIGNING_OFF, TERMINAL
> Requires: authority-and-scope, workflow-state-contract, verifier-kernel
> May load: real-runtime-stability-loop, adversarial-decision-check
> Does not own: contract compilation, implementation mechanics, domain policy, generic verification, review findings

## Activation and direct fallback

Activate only after `assess_closure_admission.py` returns `closure_eligible`. `direct_preferred` returns to standard `change-execution`; pre-freeze ambiguity, unsat, authority, environment, or verifier outcomes emit the typed admission artifact and never fabricate a full workflow.

## Immutable run invariants

Authority never expands because no human is present. Workflow identity, mode, request mode, execution policy, policy-bundle hash, frozen contract/verifier epochs, source/scope bindings, protected surfaces, and budget ceilings are immutable within an epoch. Writing owns intended state; this controller owns actual state and evidence.

## Phase state machine

The only phases are `SPEC_COMPILING`, `CONTRACT_FROZEN`, `BASELINING`, `VERIFIER_QUALIFYING`, `PLANNING`, `SEARCHING`, `SIGNING_OFF`, and `TERMINAL`. Only the controller may accept a phase transition, incumbent promotion, sign-off result, or terminal certificate through `scripts/advance_closure.py`.

## Admission

Admission is pre-workflow. It verifies machine-observable outcome, stable-enough requirements, freezable scope/authority, reproducible environment, separable verifier, bounded side effects, positive closure value, and acceptable framework tax. A request lowers no safety condition and does not create `closure_run`.

## Contract and plan handoff

Load the immutable Closure Contract and canonical Program plan from `writing-plans`; validate contract ID/hash/epoch, source/scope/policy/authority bindings, plan hash, and constraint/corner/verifier references. The controller does not edit either artifact. A material discovery produces a plan-change proposal or a new contract epoch.

## Baseline and verifier qualification

Before candidate work, freeze source/environment fingerprints, public/install entrypoints, hard-oracle baselines, known target/unrelated failures, flakiness/noise, external availability, and artifact hashes. `verifier-kernel` owns oracle authority and qualification; an unstable baseline or unqualified verifier yields its typed terminal status.

## Candidate generation and selection

Each writable candidate uses one isolated worktree, manifest, allowed/protected paths, parent/strategy identity, target counterexamples, patch hash, and bounded budget. Start with at most two parallel writers only when writes/resources and evaluation bottlenecks isolate. The controller applies the strict lexicographic comparator and alone promotes an eligible candidate.

## Counterexample-guided repair

Convert failures into replayable, constraint-preserving counterexamples. Minimize irrelevant input/trace/environment dimensions without weakening expected behavior, corners, thresholds, or entrypoints. Local product failures may create a repair candidate; harness, environment, permission, stochastic, and contract failures route to their owning recovery or terminal path.

## Invalidation and epoch changes

Contract, verifier, policy, protected threshold/golden, source/environment baseline, hidden state, public semantics, non-local failure, or root-assumption changes trigger global escalation. Field-sensitive local repair is allowed only when the invalidation graph proves all other branches and hashes remain fresh.

## Four-axis sign-off

The controller requires independent results for requirements/spec traceability, engineering quality, verifier integrity, and authority/side effects. All four must pass with fresh source, scope, contract, verifier, baseline, candidate, and review hashes. Workers and fixers cannot self-approve.

## Publication handoff

Technical `CLOSED` is independent of publication. Local patch or draft-PR handoff must stay below the frozen publication ceiling and use the appropriate host owner. Push, comment, CI rerun, approval, merge, release, and deploy remain separate authorized external actions.

## Terminal certificates

Every true closure termination emits the fixed tagged terminal artifact. `DIRECT_SELECTED` is only an admission result. `safe_next_action` is durable recovery input, not an interactive question. Only the controller commits `CLOSED` or a failure terminal state.

## Resume and crash recovery

On resume, reconcile canonical state hash/version, contiguous events, artifacts, locks, worktrees, background tasks, source/scope/policy/contract/verifier/baseline freshness, and pending proposals. Replay is idempotent; orphan work is quarantined or reconciled before new candidates start.

## Completion criterion

Completion requires a promoted incumbent, complete required cascade, four-axis sign-off, fresh immutable bindings, empty blocking state, terminal certificate, preserved recovery artifacts, and publication state recorded separately. Unit tests alone do not establish empirical P5/P6 value or release readiness.
