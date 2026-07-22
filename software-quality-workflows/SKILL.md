---
name: software-quality-workflows
description: "Use for software work only when a material boundary requires explicit evidence, authority, test-lifecycle, recovery, migration/release/install, multi-writer coordination, source freshness, or high-risk review. Skip routine known-seam edits, ordinary refactors, coding questions, prose planning, and routine documentation."
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

At a described material boundary, preserve user work, identity, scope, and authority; never invent intent or treat local proof as release proof.

Use `$writing-plans`, `$long-document-segmented-writing`, or `$skill-evaluator` for their named work; hosted owners retain remote authority.

## Default execution

Routine work stays Direct: no reference, workflow/router/card/state, JSON receipt, or ledger.

At a trigger, derive current and required behavior from bounded evidence; unknown cause permits diagnosis, not a guessed fix. Change only the owner seam: no parallel abstractions, speculative compatibility, or unrelated cleanup. Match proof to risk; strict RED is optional.

Ask only for outcome-changing intent/authority, irreversible effects, unavailable facts, or an unsound route.

## Evidence and test retention

Never weaken an oracle or keep temporary, duplicate, or implementation-coupled tests. Migration tests need an owner, observable removal condition, and gate. Load [test lifecycle](references/test/test-suite-lifecycle.md) only for material retention risk.

## Durable escalation

Durable state is only for context boundaries, destructive/external effects, staged migration/release, or multiple writers. Prefer host/repo state; otherwise one controller may use the [fallback ledger](references/control/durable-work-ledger.md). No leases, daemons, event stores, or compatibility readers.

## Optional specialist references

Load at most one owner: [authority](references/control/scope-authority-and-effects.md), [tests](references/test/test-suite-lifecycle.md), [recovery](references/recovery/repository-recovery.md), [release/install](references/domain/plugin/package-registration-and-installed-proof.md), or [review](references/review/tier-selection.md). Use the [index](references/index.md) only for another material risk. A second reference needs a separate material risk; never scan.

## Completion truth

Report only completed work and proof run; name blockers, residual risk, and unrun gates. Local completion is not commit, push, merge, release, deploy, or publication.
