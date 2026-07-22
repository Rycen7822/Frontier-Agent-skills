---
name: software-quality-workflows
description: "Use for software inspection, diagnosis, implementation, refactoring, testing, review, recovery, migration, developer tooling, or developer-facing documentation."
license: MIT
metadata:
  version: 9.0.0
  author: Hermes Agent
  hosts: [codex, hermes-agent]
  hermes:
    tags: [software-development, quality, testing, review, debugging]
    category: software-development
    related_skills: [writing-plans]
---

# Software Quality Workflows

## Scope

Own software execution truth from diagnosis through completion. Preserve user work, repository identity, and authority. Never invent intent, treat context or self-verdict as proof, or equate local proof with release readiness.

Delegate settled plans, handoffs, and rollouts to `$writing-plans`; large-source documents to `$long-document-segmented-writing`; package evaluation to `$skill-evaluator`. Hosted owners retain live remote-state authority.

## Default execution

Start with one bounded owner inventory; repeat or expand it only for a named discrepancy. Never read Git history for ordinary work; allow it only when explicitly requested or required by a concrete release/recovery/freshness conflict.

Use Direct for same-session local, reversible, single-writer work with known authority/owner and no recovery, destructive, release, production, or external effect:

1. Inspect only relevant source, tests, docs, and dirty state.
2. Diagnose unknown causes with bounded read-only evidence before editing.
3. Establish an observable current/required behavior distinction.
4. Change the smallest owner seam; add no parallel abstraction, compatibility shell, or unrelated cleanup.
5. Run proportional proof; inspect the final diff and residue.

Direct creates no workflow/router/card calls, state, JSON receipts/cards, or fallback ledger.

## Ask only for material blockers

Proceed with safe evidence-backed choices. Ask once only when missing intent or authority changes the result, an effect is dangerous or irreversible, a required fact cannot be discovered safely, or the route is demonstrably unsound. Unknown cause blocks speculative implementation, not diagnosis.

## Evidence and test retention

A behavior distinction is mandatory; strict RED is not. Use a test, focused regression, temporary probe, smoke, property check, benchmark, or real runtime evidence. Never weaken an oracle, break correct behavior, duplicate an assertion, or preserve a probe to manufacture GREEN.

Classify every test added or materially changed in the current diff exactly once:

- retain `durable_contract`, `regression`, and `risk_boundary` tests;
- retain `migration_temporary` only beside its owner, observable removal condition, and deterministic removal gate;
- remove `temporary_probe` and `duplicate` tests;
- rewrite or remove `implementation_coupled` tests.

Do not create a retention registry or review unrelated tests. Load [behavior evidence](references/test/behavior-evidence.md) only for genuine distinction or retention ambiguity.

## Durable escalation

Use durable coordination only for cross-context recovery, destructive/external effects, staged migration/release/rollout, multiple writers, or a requested recoverable audit trail. Prefer host state, then an existing repository work item. Only a single controller with neither may use the one-file [fallback ledger](references/control/durable-work-ledger.md); otherwise block. Never add leases, locks, daemons, event stores, or v4 readers.

## Optional specialist references

Default to this file. For a concrete specialist risk, read [the reference index](references/index.md) and one direct reference. Load a second only for two independent material risk surfaces. Never scan or preload the library.

## Completion truth

Complete only from fresh source/scope, accepted evidence, resolved blockers, reviewed test disposition, no pending work, and named unrun or limited gates. Report proof, residual risk, and publication ceiling. Local completion does not imply commit, push, PR, merge, release, deploy, or publication.
