---
name: software-quality-workflows
description: "Use for software work that needs explicit authority or scope control, diagnosis of an unknown failure, public-contract, security, or release handling, delegated execution, structured review, or layered verification. Routine low-risk same-session edits use the direct path without loading domain branches."
license: MIT
metadata:
  version: 4.0.0
  author: Hermes Agent
  hosts: [codex, hermes-agent]
  hermes:
    tags: [software-development, design, specifications, implementation, debugging, tdd, testing, verification, review, refactoring, security, quality, delegation, subagents]
    category: software-development
    related_skills: [writing-plans, github-workflows, long-document-segmented-writing]
---

# Software Quality Workflows

## Owner contract

This skill owns the software safety kernel, lifecycle routing, single policy ownership, and completion evidence. All software work obeys the short kernel; routine work does not need a durable workflow or the full reference stack.

## Host compatibility

Run unchanged in Codex and Hermes Agent. Resolve bundled paths from this skill's root, obey active host/system/project authority, and select each operation by capability rather than a product-specific tool name. Use only exposed capabilities; otherwise take the named local fallback or report `not_run`, `blocked`, or `inconclusive`. Product-specific adapters and metadata never redefine the kernel.

## Safety kernel

1. Preserve `report`, `diagnose`, or `change` intent; never turn inspection into edits or code authority into commit, push, deploy, install, delete, or publication authority.
2. Bound writes to the requested owner seam, preserve unrelated/dirty/concurrent work, and use only task-owned temporary resources.
3. If a failure's root cause is unknown, reproduce and diagnose before proposing implementation.
4. A behavior change needs a meaningful distinction between before and after, using the best applicable oracle rather than a ritual test shape.
5. Report only commands, runtime observations, coverage, and evidence actually obtained; separate not-run, blocked, baseline failure, and residual risk.
6. External, destructive, privileged, persistent, financial, or materially irreversible actions require explicit authority and approval.
7. Hidden/shared state, conflicting writes, stale evidence, source drift, or a changed root assumption invalidates local progress and triggers scope escalation.
8. Preserve original gate exit status, inspect the actual diff/artifact, and clean only task-owned resources.

## Workflow modes

| Mode | State | Use |
|---|---|---|
| **M0 Direct** | No durable graph; minimal in-session scope/proof | Same-session, local, reversible work with a known owner seam and focused verifier |
| **M1 Trace** | Record observed actions/evidence only; do not alter strategy | Shadow telemetry or uncertain activation value |
| **M2 Sparse** | Persist only costly, parallel, approval, external-state, cache, or independent-proof boundaries | Delegated slices, public contracts, expensive gates, or useful local recovery |
| **M3 Full** | Durable typed workflow, lineage, locks, resume, invalidation, and repair | Multi-session migration/release/recovery, shared state, or strong audit requirements |

Use the lightest mode that preserves authority, proof, recovery, and auditability. File count, line count, a subjective complexity label, long context, or available subagents do not independently justify escalation.

Load full [Authority and Scope](references/authority-and-scope.md) only for report/review coverage, dirty or concurrent work, delegation, external/persistent/destructive/privileged actions, recovery, uncertain revision, or disputed scope/risk. M0 keeps a minimal scope record without creating a manifest unless persistence or ambiguity requires one.

## Route order

1. Apply the kernel and preserve request mode.
2. Read-only report/review stays read-only; unknown failures route to diagnosis; underdefined outcomes route to intent discovery.
3. Select M0–M3 from observable risk, handoff, resume, external-state, verification-cost, and failure-locality facts.
4. Use one primary lifecycle owner; add only concretely triggered domain/evidence supplements.
5. Use `writing-plans` only for explicit or durable plan needs; a known local bug can move directly from diagnosis to M0.
6. Enter autonomous closure only from an explicit request plus deterministic admission; otherwise keep `execution_policy: standard`.
7. Escalate authority/state when a guard fires; close with scoped evidence and explicit gaps.

## Autonomous closure boundary

Autonomous closure is an execution policy, not a fifth workflow mode. First run the bounded admission contract in [Autonomous Closure](references/autonomous-closure.md). An eligible request requires a frozen Closure Contract and contract-bound Program/Migration Map from `writing-plans`; missing authority, intent, scope, environment, verifier separability, or bounded side effects returns a typed terminal or standard fallback.

The deterministic controller is the only phase, promotion, terminal, or `CLOSED` authority. Workers may propose candidates, counterexamples, verification requests, and blockers; they cannot modify the contract, controller, verifier kernel, holdouts, or publication ceiling. [Verifier Kernel](references/verifier-kernel.md) qualifies and freezes independent evidence before search. Candidate work uses isolated local worktrees, fresh integration replay, and requirements, engineering, verifier-integrity, and authority sign-off. P4 permits local patches only: no merge, push, release, deploy, or other remote write.

Live host-agent execution and multi-candidate search are default-off. A capability-qualified adapter may execute one local candidate under the frozen sandbox and scope; output stays diagnostic until schema, snapshot, artifact, and controller validation accepts it. The Codex adapter is optional. Capacity, authentication, timeout, cancellation, drift, and partial changes produce typed failures rather than implicit retries or user-wait loops.

## Mode-aware lifecycle

| Lifecycle | Sequence |
|---|---|
| Report/review | scope/coverage → inspect → findings/evidence → close; no edits |
| Diagnose | reproduce → localize → falsifiable hypothesis → evidence → report or authorized change |
| Direct change | contract → focused distinction → smallest coherent change → diff inspection → proportional affected proof |
| Planned change | current frontier → proof-first slice → implementation → verification → state refresh → integration/close |
| Recovery | detect drift/failure → classify → invalidate affected state → local repair or escalation → reverify |

Intent discovery, D0/D1/D2 design audit, durable planning, delegation, independent review, and full authority are guarded transitions, not universal steps.

## Policy ownership

| Role | Policy | Single normative owner |
|---|---|---|
| Safety/scope | Mode, authority, risk, scope, coverage, temporary resources | [Authority and Scope](references/authority-and-scope.md) |
| Primary lifecycle | Underdefined outcome and specification formation | [Intent and Design Discovery](references/intent-and-design-discovery.md) |
| Primary lifecycle | Diagnosis and bugfix ordering | [Systematic Debugging](references/systematic-debugging.md) |
| Primary lifecycle | Authorized standard change execution | [Change Execution](references/change-execution.md) |
| Primary lifecycle | Contract-bound autonomous search and closure | [Autonomous Closure](references/autonomous-closure.md) |
| Control plane | Oracle qualification, freeze, and independence | [Verifier Kernel](references/verifier-kernel.md) |
| Mechanism | RED/GREEN/REFACTOR and proof-first test mechanics | [Test-Driven Development](references/test-driven-development.md) |
| Evidence | Gates, evidence labels, original exit status, completion proof | [Verification Discipline](references/verification-discipline.md) |
| Primary lifecycle | Review orchestration, tier, and coverage | [Requesting Code Review](references/requesting-code-review.md) |
| Primary lifecycle | Delegated execution and controller/child authority | [Delegated Development](references/delegated-development.md) |
| Review | Requirement traceability | [Requirements Traceability Review](references/requirements-traceability-review.md) |
| Review | Finding fields, severity, verdicts, approvals | [Review Result Schema](references/review-result-schema.md) |
| Evidence | Test purpose, provenance, lifecycle, retirement | [Test Lifecycle Management](references/test-lifecycle-management.md) |
| Domain | Security trust boundaries and abuse | [Security Hardening](references/security-hardening.md) |
| Domain | API/schema/protocol compatibility | [API and Interface Design](references/api-interface-design.md) |
| Domain | Internal modules, seams, dependencies, decisions | [Architecture and Module Design](references/architecture-module-design.md) |
| Domain | Logs, metrics, traces, health, progress | [Observability Instrumentation](references/observability-instrumentation.md) |
| Domain | Performance baseline and result parity | [Performance Optimization](references/performance-optimization.md) |
| Domain | Browser runtime evidence | [Browser Runtime Verification](references/browser-runtime-verification.md) |
| Domain | Plugin source/build/package/registration/public layers | [Plugin Quality](references/plugin-quality.md) |
| Domain evidence | Installed provenance, fresh loader/process, neutral-context proof | [Plugin Installed Surface](references/plugin-installed-surface.md) |
| Recovery | Merge/rebase/cherry-pick/revert conflict intent | [Merge Conflict Resolution](references/merge-conflict-resolution.md) |

Other references may add questions, invariants, or proof, but may not redefine authority, lifecycle order, or closure.

## Review tiers

- **R0:** routine M0; self-diff inspection plus the applicable verifier, no automatic independent reviewer.
- **R1:** M2/cross-component/non-trivial owner change; requirement/spec axis then engineering-quality axis.
- **R2:** public contract, security, release, or high risk; independent review and, when justified, bounded adversarial checking.

Implementers/fixers do not self-approve high-risk work. Reviewer count is not a quality metric.

## Progressive disclosure and reference budget

Default active stack: kernel + one primary lifecycle owner + zero or one domain owner + zero or one evidence/review owner. More than three external references is a soft warning, not a hard cap; record concrete reason codes for every additional owner.

Use the machine-readable [owner registry](references/owner-registry.json) to select the exact owner from positive triggers and exclusions. The registry is the complete flat reference catalog; the entry keeps only the high-frequency branch map:

| Trigger family | Route |
|---|---|
| Unknown failure or unexpected behavior | diagnosis owner; implementation remains blocked until root cause is supported |
| Underdefined intent or materially different outcomes | intent/design owner, then `writing-plans` only if a durable implementation plan is needed |
| Authorized behavior change | TDD mechanism plus proportional verification |
| Public/security/architecture/performance/plugin boundary | the matching domain owner |
| Review, traceability, or structured finding work | the matching review/evidence owner and R0/R1/R2 tier |
| Resume, delegation, or cross-session coordination | M2/M3 state contract; delegation only when authorized |
| Prototype, spike, disposable experiment, task scratch, or staging artifact | artifact-hygiene owner; no implied production lift |
| Recovery or conflict work | the matching recovery owner before ordinary implementation resumes |

Do not scan or load the full catalog pre-emptively. A selected branch records its owner ID and reason code; exclusions and `must_not_load` take precedence over keyword overlap.

## External owners

- `writing-plans` owns explicit implementation-plan requests and durable cross-session/delegated handoff, dependency, migration/rollback, or staged-proof plans. It does not own routine direct edits or unresolved diagnosis.
- `long-document-segmented-writing` owns large-corpus inventory, segmented drafting, reread, and document recovery; SQW supplies software quality/provenance questions.
- `github-workflows` owns live hosted-platform metadata and authorized remote writes. Code authority never implies hosted-write authority.
- Unavailable owners do not silently remove a gate; use a bounded local fallback or report `blocked`/`inconclusive`.

## Support resources

| Resource | Purpose |
|---|---|
| [Independent reviewer prompt](templates/requesting-code-review/independent-reviewer-prompt.md) | Scoped read-only review |
| [Scoped fixer prompt](templates/requesting-code-review/fix-agent-prompt.md) | Allowlisted fixes; no self-approval |
| [Design spec reviewer](templates/design-discovery-spec-reviewer-prompt.md) | Optional spec-readiness review |
| [Design server](scripts/design-discovery/server.cjs) | Local visual companion |
| [Design start](scripts/design-discovery/start-server.sh) | Tracked launcher |
| [Design stop](scripts/design-discovery/stop-server.sh) | Scoped cleanup |
| [Contract validator](scripts/validate_skill_contracts.py) | Policy/package checks |
| [Owner registry](references/owner-registry.json) | Owner routing catalog |
| [Workflow modes](references/workflow-modes.md) | M0–M3 boundaries |
| [Workflow state](references/workflow-state-contract.md) | State/events/closure |
| [Context projection](references/context-projection.md) | Bounded capsules |
| [Repair](references/repair-and-invalidation.md) | Invalidation and repair |
| [Local adapter](adapters/local-filesystem.md) | Atomic M2/M3 storage |
| [Codex adapter](adapters/codex-exec.md) | Optional Codex execution |
| [Plugin gate](adapters/plugin-runtime.md) | Deferred activation |
| [Workflow router](scripts/route_workflow.py) | Mode/owner selection |
| [Closure admission](scripts/assess_closure_admission.py) | Closure eligibility |
| [Closure controller](scripts/advance_closure.py) | Sole transition authority |
| [Verifier validator](scripts/validate_verifier_bundle.py) | Verifier qualification |
| [State validator](scripts/validate_workflow_state.py) | State/event checks |
| [Frontier calculator](scripts/compute_frontier.py) | Ready/blocked nodes |
| [Context projector](scripts/project_context.py) | Capsule renderer |
| [Invalidation calculator](scripts/propagate_invalidation.py) | Affected-state report |
| [Workflow reconciler](scripts/reconcile_workflow.py) | Resume drift |
| [Adapter script](scripts/local_workflow_adapter.py) | State operations |

## Completion contract

- **M0:** report changed scope/diff, focused and proportional affected proof, not-run/blocked/baseline evidence, and residual risk.
- **M1:** M0 completion plus trace capture status; trace does not upgrade proof.
- **M2/M3:** reconcile source/scope freshness, state/frontier, running/background work, locks/approvals, evidence, invalidation/repair, and closure.
- Use `closure_status: complete | incomplete | inconclusive`, plus `epistemic_status: needs_repair | verified_within_scope | blocked | empirical_validation_required`, covered scope, evidence freshness, known gaps, external uncertainty, and empirical validation needs.
- Local technical success does not imply merge, deployment, publication, or human approval readiness.
