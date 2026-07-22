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

Use only for a material boundary in the description. Preserve user work, identity, scope, and authority. Never invent intent or treat local/self-verdict as release proof.

Return planning to `$writing-plans`, large documents to `$long-document-segmented-writing`, and package evaluation to `$skill-evaluator`; hosted owners retain remote authority.

## Default execution

Routine known-seam work stays Direct with no reference or workflow/router/card/state/JSON receipt/ledger.

For a triggered boundary, establish current and required behavior from bounded evidence. Unknown cause permits diagnosis, never a guessed fix. Change the smallest owner seam without parallel abstractions, speculative compatibility, or unrelated cleanup. Match proof to risk; strict RED is optional when another distinction is stronger.

## Ask only for material blockers

Ask only when intent or authority changes the result, an effect is dangerous or irreversible, a fact cannot be found safely, or the route is unsound.

## Evidence and test retention

Never weaken an oracle or retain temporary, duplicate, or implementation-coupled tests. A migration-only test needs an owner, observable removal condition, and gate. Load [test lifecycle](references/test/test-suite-lifecycle.md) only when retention is material.

## Durable escalation

Use durable state only for a context boundary, destructive/external effect, staged migration/release, or multiple writers. Prefer host/repository state; otherwise only a single controller may use the [fallback ledger](references/control/durable-work-ledger.md). Never add leases, daemons, event stores, or compatibility readers.

## Optional specialist references

Load at most one boundary owner: [authority](references/control/scope-authority-and-effects.md), [tests](references/test/test-suite-lifecycle.md), [recovery](references/recovery/repository-recovery.md), [release/install](references/domain/plugin/package-registration-and-installed-proof.md), or [review](references/review/tier-selection.md). Use the [index](references/index.md) only for another named risk. A second reference requires two independent material risks; never scan.

## Completion truth

Report only completed work and proof actually run; name blockers, residual risk, and unrun gates. Local completion does not imply commit, push, merge, release, deploy, or publication.
