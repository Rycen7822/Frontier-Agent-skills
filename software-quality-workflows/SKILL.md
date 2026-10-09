---
name: software-quality-workflows
description: Apply explicitly requested engineering-quality guidance to implementation and maintenance work.
license: MIT
metadata:
  version: 13.1.0
  author: Hermes Agent
  hosts: [codex, hermes-agent]
  hermes:
    tags: [software-development, quality, implementation, review, debugging]
    category: software-development
    related_skills: [writing-plans, test-behavior]
---

# Software Quality Workflows

Understand current behavior and the requested outcome, then make the smallest complete change. Follow relevant owners and callers; preserve user work and actual compatibility commitments. Clear tasks need no preliminary specification or mandatory workflow stages.

## Implementation

Prefer existing architecture and data shapes. Keep related state and invariants together; reduce duplicated decisions, unnecessary indirection and hidden mutable state. Add abstractions, configuration or dependencies only for a current need. Favor clear control flow and retain explanations of non-obvious constraints.

Clarify observable behavior when APIs, data, errors or cross-cutting changes make it consequential. Tests, plans, specifications and evaluators are editable within the requested scope; a failing check alone does not authorize weakening its requirement.

## Evidence and tests

Verify affected claims after a coherent edit; preserve a useful pre-change baseline when comparison needs it. Reuse evidence while relevant behavior, dependencies, environment and consumer remain valid. Obvious semantic no-ops usually need no rerun or model evaluation. Otherwise use the lowest-cost deciding check, covering changed behavior and the nearest protected control. Use the final consumer when internal checks cannot establish the claim.

Apply [Test Behavior](../test-behavior/SKILL.md) before writing or modifying any check code or script, including temporary reproductions, inline probes, helpers, fixtures and installation or migration checks. It owns whether and when to write, valid expectations, permanent placement and retirement. Also apply it when the task removes or replaces a behavior contract, completes a migration or ends a compatibility obligation, even if no test edit is planned. SQW remains responsible for the overall implementation; running existing checks alone needs no new tests.

Classify failures as product, expectation, setup/environment, unrelated or unknown before changing another surface. An unavailable dependency or provider timeout leaves behavior unobserved. Retry only when a changed hypothesis, input, setup or independent observation could change the conclusion.

## Completion

Continue until the requested outcome is complete and sufficiently verified. Existing user authorization persists; a skill default or completed phase does not create a new approval requirement. If one action needs missing input or authority, finish independent authorized work and report the specific remaining dependency. Respect review-only or analysis-only requests.

Reuse current context and task state. Select specialized skills when their distinct method helps, without loading a pipeline. Delegate only when authorized and useful. If verification changes delivered state, confirm the resulting state before handoff. Report the outcome, decisive evidence and material limits; distinguish local verification from external publication when relevant.

For material behavior changes, explain the before/after behavior, affected consumers and meaningful rollback limits using available evidence. Distinguish source-based expectations from observed runs, and identify an unavailable baseline. Scale detail and visual aids to the change.

Read further only for a concrete need:

- [Scope and evidence](references/scope-and-evidence.md): ownership, external effects or evidence validity.
- [Test Behavior](../test-behavior/SKILL.md): authored checks or affected protection when a behavior obligation ends; the [former testing reference](references/testing.md) points to the same owner.
- [Collaboration and state](references/collaboration-and-state.md): multiple writers, recovery or resource ownership.
- [Repository recovery](references/recovery.md): conflicts or interrupted repository operations.
