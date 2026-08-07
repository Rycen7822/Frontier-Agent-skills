---
name: software-quality-workflows
description: Use when software work has a material boundary in evidence, authority, ownership, source, or effects.
license: MIT
metadata:
  version: 9.0.1
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

Owner seam is the smallest code/API/config/test/component controlling behavior, not repository ownership unless provenance is requested.

For a bound read-only/local-only target with forbidden effects, inspect minimal in-scope evidence; do not inspect Git provenance or widen inventory unless source identity is material.

Load [authority](references/control/scope-authority-and-effects.md) only for unresolved write scope; protected/dirty/concurrent work; destructive/external/privileged effects; material source root/revision; multiple owners/writers; or authorization for the proposed effect.

Otherwise derive behavior from bounded evidence; unknown cause permits diagnosis, not a guessed fix. Change only the owner seam—no parallel abstraction, speculative compatibility, unrelated cleanup, routine owner inventory, or fixed process/RED/report. Match proof to risk; ask only for outcome-changing authority, irreversible effects, unavailable facts, or an unsound route.

A settled exact disposition is binding: perform or describe it; no retention, compatibility, or alternative branches.

## Evidence and test retention

Keep only durable-contract, confirmed-regression, or risk-boundary tests. Remove a test whose sole owner is retired behavior; retarget it only when replacement coverage is explicitly required. Load [test lifecycle](references/test/test-suite-lifecycle.md) only for material retention or migration risk.

## Durable escalation

Use durable state only across contexts, for destructive/external effects, staged migration/release, or multiple writers. Prefer host/repo state; otherwise use one controller's [fallback ledger](references/control/durable-work-ledger.md). No leases, daemons, event stores, or compatibility readers.

## Optional specialist references

For one material risk load at most one: [tests](references/test/test-suite-lifecycle.md), [recovery](references/recovery/repository-recovery.md), [release/install](references/domain/plugin/package-registration-and-installed-proof.md), or [review](references/review/tier-selection.md). Use the [index](references/index.md) only if none fits; never scan. A second needs a distinct risk.

## Completion truth

Report only completed work and proof run; name blockers, residual risk, and unrun gates. Local completion is not commit, push, merge, release, deploy, or publication.
