---
name: software-quality-workflows
description: "Use when software work has a material boundary in evidence, authority, ownership, source, or effects."
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

At material boundaries preserve work, scope, and authority; never invent intent or equate local with release proof.

## Default execution

Known-seam work stays Direct: no reference, workflow/router/card/state, JSON receipt, or ledger.

Owner seam means the smallest code/API/config/test/component controlling behavior, not Git authorship, filesystem owner, repo objects, or ancestry unless provenance is requested.

For a bound read-only/local-only target and forbidden effects, inspect minimal evidence inside it. Do not load [authority](references/control/scope-authority-and-effects.md), inspect Git authors/config/refs/objects, or widen inventory unless provenance or source identity is material.

Load authority only for unresolved write scope; protected/dirty/concurrent work; destructive/external/privileged effects; material source root/revision; multiple owners/writers; or authorization for the proposed effect.

Otherwise derive current and required behavior from bounded evidence; unknown cause permits diagnosis, not a guessed fix. Change only the owner seam: no parallel abstraction, speculative compatibility, or unrelated cleanup. Match proof to risk. No routine owner inventory or fixed process/RED/report. Ask only for outcome-changing authority, irreversible effects, unavailable facts, or an unsound route.

## Evidence and test retention

Keep only durable-contract, confirmed-regression, or risk-boundary tests; remove temporary, duplicate, or implementation-coupled tests without weakening oracles. Migration tests need an owner, observable removal condition, and gate. Load [test lifecycle](references/test/test-suite-lifecycle.md) only for material retention risk.

## Durable escalation

Use durable state only across contexts, for destructive/external effects, staged migration/release, or multiple writers. Prefer host/repo state; otherwise use one controller's [fallback ledger](references/control/durable-work-ledger.md). No leases, daemons, event stores, or compatibility readers.

## Optional specialist references

For one material risk load at most one: [tests](references/test/test-suite-lifecycle.md), [recovery](references/recovery/repository-recovery.md), [release/install](references/domain/plugin/package-registration-and-installed-proof.md), or [review](references/review/tier-selection.md). Use the [index](references/index.md) only if none fits; never scan. A second needs a distinct risk.

## Completion truth

Report only completed work and proof run; name blockers, residual risk, and unrun gates. Local completion is not commit, push, merge, release, deploy, or publication.
