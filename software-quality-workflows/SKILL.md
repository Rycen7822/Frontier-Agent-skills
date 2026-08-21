---
name: software-quality-workflows
description: Use when software work has a material boundary in evidence, authority, ownership, source, or effects.
license: MIT
metadata:
  version: 11.0.0
  author: Hermes Agent
  hosts: [codex, hermes-agent]
  hermes:
    tags: [software-development, quality, testing, review, debugging]
    category: software-development
    related_skills: [writing-plans]
---

# Software Quality Workflows

## Native default

Preserve work, scope, authority, and evidence at material boundaries. Bind claims to their oracle, coverage, freshness, limitations, and raw reference. The owner seam is the smallest code/API/config/test/component controlling behavior.

Keep known-seam work Direct and change its smallest coherent owner set. Resolve prompt-bound paths and establish their working directory before consuming a command attempt. Copy a bound command verbatim, execute it from that directory, and count every attempted invocation, including a shell-start failure, against its declared run budget. Rediscover only on binding failure or conflict.

## Observable contract

Before cross-cutting/API/data/error/migration work, freeze input/output, invariants, errors, compatibility, and non-goals. Verify each owner independently, including upstream-masked behavior; a composed happy path is insufficient.

## Evidence selection

Complete coherent edits before proof. If no conclusion-changing risk or gate remains, close. Otherwise use the lowest deciding evidence, escalating from inspection/direct examples through focused/affected checks to integration or high-cost gates. Cover changed behavior and its nearest protected control; filtering proof covers retained values and order.

Load [authority](references/control/scope-authority-and-effects.md) when effects, protected work, source identity, or writers are unresolved.

## Failure ownership

Classify a failed check before another edit:

- `task_regression`: repair the owned seam; rerun deciding evidence.
- `authorized_contract_change`: synchronize implementation and oracle to named authority.
- `invalid_oracle_or_test`: preserve product behavior until independent authority establishes the oracle.
- `harness_setup_environment`: repair within scope, or narrow the claim using independent evidence.
- `preexisting_or_unrelated`: preserve baseline; implementation may complete with verification partial/blocked.
- `stochastic`: follow the predeclared seed/state, trial limit, and decision rule.
- `unknown`: run one cheap discriminator; finish inconclusive if ownership stays unknown.

## Progress stop

Use `(command_sha256, exit_code, output_sha256)` for command failures. In one unchanged workspace/trial state, run an identical failure at most twice. The `repeated` label needs two bound observations; a prior may be first. Continue only when hypothesis, owner, signature, or independent observation changes. If a discriminator changes none, stop `verification_blocked` or `verification_inconclusive`. Host/provider timeout is unobserved apparatus.

## Test retention

Classify only new or changed tests with unclear disposition. Keep stable contracts, regressions, and material risk boundaries; remove probes, duplicates, and retired-behavior tests. Use strict test-first only when required, oracle and harness are sound, behavior is narrow/fast, and a stop budget is fixed. Load [test lifecycle](references/test/test-suite-lifecycle.md) for material migration risk.

## Completion truth

Create durable state or a digest only for a cross-context consumer, external effect, staged release, or multiple writers. Prefer host/repo state; otherwise use one [fallback ledger](references/control/durable-work-ledger.md). Route other risks through the [index](references/index.md).

Report success naturally. When states diverge, report `implementation: complete | partial | blocked`, `verification: verified | partial | blocked | inconclusive`, and `release: not_claimed | eligible_only_after_named_gates`. Unrelated red preserves completed implementation; local proof grants no release authority.
