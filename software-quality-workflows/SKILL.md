---
name: software-quality-workflows
description: Implement and verify changes with proportionate evidence and failure attribution.
license: MIT
metadata:
  version: 11.0.1
  author: Hermes Agent
  hosts: [codex, hermes-agent]
  hermes:
    tags: [software-development, quality, testing, review, debugging]
    category: software-development
    related_skills: [writing-plans]
---

# Software Quality Workflows

## Native default

Start with the requested observable outcome. Read the directly relevant product code, make the smallest coherent change, run the nearest meaningful verification, and stop. Diagnose and review requests remain read-only unless the user also asks for a change.

Specs, plans, slice definitions, evaluators, harnesses, release controllers, policies, goldens, and evidence generators are support or control surfaces. Leave them unchanged unless explicitly requested or themselves the shipped product. Their failure limits verification; it does not expand the task.

Honor bound paths, working directories, exact commands, and attempt budgets. A command that cannot reach the intended product surface is setup or harness failure, not product evidence.

## Observable contract

For cross-cutting, API, data, error, or migration work, state existing behavior, requested difference, compatibility, and non-goals. Use an existing specification; do not create or freeze one unless requested.

## Evidence selection

Complete coherent edits before proof. If no conclusion-changing risk or gate remains, close. Otherwise use the lowest deciding evidence, escalating only when needed. Cover changed behavior and its nearest protected control; filtering proof covers retained values and order.

Load [authority](references/control/scope-authority-and-effects.md) when effects, protected work, source identity, or writers are unresolved.

## Failure ownership

Classify a failed check before another edit:

- `product`: repair the direct implementation and rerun deciding evidence.
- `contract_or_oracle`: preserve product behavior until the requirement or oracle is authoritative.
- `harness_or_environment`: setup, fixture, permission, runner, provider, or environment failed before a product conclusion.
- `unrelated`: preserve the baseline and report without expanding the task.
- `unknown_or_stochastic`: run one cheap discriminator or bounded trial, then finish inconclusive.

For continuity, use the existing Markdown worklog and record `Failure`, `Class`, command or operation, decisive error or log path, and `Decision`. Do not hash commands or outputs for retry control or traceability. A support/control failure does not authorize modifying it.

## Progress stop

In one unchanged workspace or trial state, run the same failing check at most twice. Judge sameness from operation, cause, and decisive error—not byte identity. Continue only when a change, hypothesis, setup, or independent observation could alter the conclusion. Otherwise stop `verification_blocked` or `verification_inconclusive`. Host or provider timeout is unobserved apparatus.

## Test retention

Classify only new or changed tests with unclear disposition. Keep stable contracts, regressions, and material risk boundaries; remove probes, duplicates, and retired-behavior tests. Use strict test-first only when required and the oracle and harness are sound. Load [test lifecycle](references/test/test-suite-lifecycle.md) for material migration risk.

## Completion truth

Prefer existing host or repository state. Use one [fallback ledger](references/control/durable-work-ledger.md) only for cross-context recovery, external effects, staged release, multiple writers, or an explicit audit trail; ordinary work creates neither ledger nor digest. Route other risks through the [index](references/index.md).

Lead with the requested outcome; put failure attribution and limits after it. When states diverge, distinguish implementation, verification, and release without creating a new control protocol. Unrelated red preserves completed implementation; local proof grants no release authority.
