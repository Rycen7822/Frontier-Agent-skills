---
name: software-quality-workflows
description: Use when software work has a material boundary in evidence, authority, ownership, source, or effects.
license: MIT
metadata:
  version: 10.0.0
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

Preserve readable evidence and its raw authority. A digest proves only that bound bytes match; it never replaces semantic content, coverage, freshness, producer, oracle, command/status, limitations, or evidence references.

## Default execution

Known-seam work stays Direct: no reference, workflow/router/card/state, JSON receipt, ledger, or digest calculation/reporting without a real cross-boundary consumer.

Owner seam is the smallest code/API/config/test/component controlling behavior, not repository ownership unless provenance is requested.

For a bound read-only/local-only target with forbidden effects, inspect minimal in-scope evidence; do not inspect Git provenance or widen inventory unless source identity is material.

Load [authority](references/control/scope-authority-and-effects.md) only for unresolved write scope; protected/dirty/concurrent work; destructive/external/privileged effects; material source root/revision; multiple owners/writers; or authorization for the proposed effect.

Otherwise derive behavior from bounded evidence; unknown cause permits diagnosis, not a guessed fix. Change only the owner seam—no parallel abstraction, speculative compatibility, unrelated cleanup, routine owner inventory, or fixed process/RED/report. Match proof to risk. Behavior proof covers the intended change and its nearest protected control; for filtering, verify retained values and order. A one-sided check cannot support a two-sided claim. Ask only for outcome-changing authority, irreversible effects, unavailable facts, or an unsound route.

A settled exact disposition is binding: perform or describe it; no retention, compatibility, or alternative branches.

## Evidence and test retention

Keep durable-contract, confirmed-regression, or risk-boundary tests. Delete tests that import/call only retired behavior; a replacement does not authorize retargeting. Retarget only for explicit replacement coverage. Load [test lifecycle](references/test/test-suite-lifecycle.md) only for material retention/migration risk.

## Durable escalation

Use durable state only across contexts, for destructive/external effects, staged migration/release, or multiple writers. Prefer host/repo state; otherwise use one controller's [fallback ledger](references/control/durable-work-ledger.md). No leases, daemons, event stores, or compatibility readers.

## Optional specialist references

For one material risk load at most one: [tests](references/test/test-suite-lifecycle.md), [recovery](references/recovery/repository-recovery.md), [release/install](references/domain/plugin/package-registration-and-installed-proof.md), or [review](references/review/tier-selection.md). Use the [index](references/index.md) only if none fits; never scan. A second needs a distinct risk.

## Completion truth

Report only completed work and proof run; name blockers, residual risk, and unrun gates. Local completion is not commit, push, merge, release, deploy, or publication.
