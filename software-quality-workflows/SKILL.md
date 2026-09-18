---
name: software-quality-workflows
description: Apply explicitly requested engineering-quality guidance to implementation and maintenance work.
license: MIT
metadata:
  version: 13.0.0
  author: Hermes Agent
  hosts: [codex, hermes-agent]
  hermes:
    tags: [software-development, quality, testing, review, debugging]
    category: software-development
    related_skills: [writing-plans]
---

# Software Quality Workflows

Understand current behavior and the requested outcome, then make the smallest complete change. Follow relevant owners and callers; preserve user work and actual compatibility commitments. Clear tasks need no preliminary specification or mandatory workflow stages.

## Implementation

Prefer existing architecture and data shapes. Keep related state and invariants together; reduce duplicated decisions, unnecessary indirection and hidden mutable state. Add abstractions, configuration or dependencies only for a current need. Favor clear control flow and retain explanations of non-obvious constraints.

Clarify observable behavior when APIs, data, errors or cross-cutting changes make it consequential. Tests, plans, specifications and evaluators are editable within the requested scope; a failing check alone does not authorize weakening its requirement.

## Evidence and tests

Finish coherent edits before verification. Reuse evidence while relevant behavior, dependencies, environment and consumer remain valid. Obvious semantic no-ops usually need no rerun or model evaluation. Otherwise use the lowest-cost deciding check, covering changed behavior and the nearest protected control. Use the final consumer when internal checks cannot establish the claim.

Apply YAGNI to tests. Keep unique protection for stable behavior, regressions and material risks; extend existing coverage when useful. Remove duplicates, retired expectations and incidental prompt-wording assertions. Keep one-off probes temporary. Test-first is conditional on a useful, affordable oracle.

Classify failures as product, expectation, setup/environment, unrelated or unknown before changing another surface. An unavailable dependency or provider timeout leaves behavior unobserved. Retry only when a changed hypothesis, input, setup or independent observation could change the conclusion.

## Completion

Continue until the requested outcome is complete and sufficiently verified. Existing user authorization persists; a skill default or completed phase does not create a new approval requirement. If one action needs missing input or authority, finish independent authorized work and report the specific remaining dependency. Respect review-only or analysis-only requests.

Reuse current context and task state. Select specialized skills when their distinct method helps, without loading a pipeline. Delegate only when authorized and useful. If verification changes delivered state, confirm the resulting state before handoff. Report the outcome, decisive evidence and material limits; distinguish local verification from external publication when relevant.

Read further only for a concrete need:

- [Scope and evidence](references/scope-and-evidence.md): ownership, external effects or evidence validity.
- [YAGNI testing](references/testing.md): oracle independence or test retention.
- [Collaboration and state](references/collaboration-and-state.md): multiple writers, recovery or resource ownership.
- [Repository recovery](references/recovery.md): conflicts or interrupted repository operations.
