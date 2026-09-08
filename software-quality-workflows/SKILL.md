---
name: software-quality-workflows
description: Guide feature implementation, known-cause fixes, test strategy and general software development with minimal necessary process. Keep designs simple, changes complete and evidence proportionate; specialized investigation, design, diagnosis, review and simplification have direct task skills.
license: MIT
metadata:
  version: 12.0.0
  author: Hermes Agent
  hosts: [codex, hermes-agent]
  hermes:
    tags: [software-development, quality, testing, review, debugging]
    category: software-development
    related_skills: [writing-plans]
---

# Software Quality Workflows

## Native default

Understand current behavior and the requested outcome, read relevant owners and callers, then make the smallest complete change. Clear tasks need no preliminary specification or workflow ceremony. Preserve user work and actual compatibility commitments. Diagnosis and review remain read-only unless changes are requested.

Use existing architecture and data shapes when they serve the task. Keep related state and invariants together; reduce unnecessary indirection, duplicated decisions and hidden mutable state. Add abstractions, configuration, dependencies or durable automation only for a current need. Prefer clear control flow to clever compression, and retain explanations of non-obvious reasons and constraints.

Specs, plans, tests, evaluators and release controls are editable when requested or when they are the product. A failing control does not itself authorize changing that surface. Honor bound paths, commands and budgets; a command that never reaches the product cannot establish its behavior.

## Observable contract

For API, data, error or cross-cutting changes, clarify current behavior, requested differences and actual compatibility. Reuse existing requirements; persist a new specification only when needed.

## Evidence selection

Complete coherent edits before verification. Reuse evidence while relevant behavior, dependencies and environment remain valid; obvious semantic no-ops usually need no rerun or model evaluation. Otherwise run the lowest-cost deciding check after the last relevant change. Cover changed behavior and the nearest protected control; use the final consumer when internal checks are insufficient. If verification changes delivered state, confirm that state before handoff.

## Failure ownership

Classify failure as product, contract/oracle, harness/environment, unrelated or still unknown before another edit. A file outside the diff can still be affected indirectly. Repair an authorized product defect; preserve requirements when an oracle is uncertain; treat unavailable setup or provider timeout as unobserved behavior.

## Progress stop

Avoid repeated unchanged failures. Continue only when a changed hypothesis, input, setup or independent observation could change the conclusion. Otherwise state the missing evidence and stop the blocked verification path without discarding completed work. Do not weaken checks for a pass.

## Test retention

Apply YAGNI to tests: retain unique protection for stable behavior, regressions and material risks; extend existing coverage when possible. Do not add implementation mirrors or incidental prompt-wording assertions. Keep one-off probes temporary, remove duplicates and retire tests for removed behavior. Test-first is conditional on a useful, affordable oracle.

## Completion truth

Use existing state and already valid context. Delegate only with authorization and a concrete net benefit; no fixed roles, models or reviewer counts. Specialized skills can be selected directly when their distinct method helps; do not load a pipeline or reread shared guidance already in context.

Use only the relevant reference when detail is needed:

- [Scope and evidence](references/scope-and-evidence.md): protected work, external effects or evidence validity is uncertain.
- [YAGNI testing](references/testing.md): test value, oracle independence or suite cleanup needs judgment.
- [Collaboration and state](references/collaboration-and-state.md): multiple writers, cross-context recovery or resource ownership.
- [Repository recovery](references/recovery.md): actual conflicts or damaged/interrupted repository operations.

Report the outcome, decisive evidence and material limits in language the reader needs. Distinguish implementation, verification and external publication when relevant. Stop when the request is complete and sufficiently verified; local proof does not itself grant release authority.
