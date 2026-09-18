---
name: code-simplifier
description: Simplify user-selected code for clarity and lower maintenance burden while preserving intended behavior; not a mandatory post-edit cleanup.
license: Apache-2.0
metadata:
  version: 1.2.0
  hosts: [codex, hermes-agent]
---

<!-- Modified for FAS 1.2.0, 2026-09-18: evidence-led structural simplification and conditional validation. -->

# Code Simplifier

## Scope and behavior

Use the user-selected component, files or change; default to recently modified code only when no wider scope is named. For change-based work, resolve the actual comparison base rather than assuming a branch name. Keep audit-only requests read-only. Read relevant implementation and consumers, including outside the edit scope, without treating inspection as permission to modify them. Preserve user work and repository conventions.

Preserve intended outputs, side effects, errors, compatibility and relevant ordering, lifetime and performance contracts. Explicitly requested removal or behavior changes follow the user's goal; otherwise do not retire supported behavior or mix unrelated bug fixes into simplification. Resolve only consequential missing authority or contract uncertainty; continue independent authorized work.

## Choose a useful change

Reduce what a reader must trace: unnecessary indirection, scattered invariants, redundant branches, duplicated transformations and hidden mutable state. Prefer direct control flow, cohesive ownership and fewer representations. Before a nontrivial structural change, briefly establish the current burden, affected consumers, owner after removal, a counterexample that would invalidate it, and the smallest decisive check. Existing task context can supply this explanation; do not create a mandatory form, plan file or confidence score.

Check that the burden disappears rather than moving into callers, configuration, tests or runtime coordination. Do not replace an unnecessary abstraction with another wrapper, couple unrelated cases to remove similar text, or optimize for line count. Keep useful names, abstractions, non-obvious rationale, contracts and licensing. Do not infer dead code from zero search matches.

## Load detail only when needed

Use [structural simplification](references/structural-simplification.md) when a candidate changes shared ownership, state or representations, compatibility, registrations, generated consumers or lifecycle behavior; it also covers explicitly requested broad audits. Stay on the local path for straightforward edits.

Use [validation](references/validation.md) when equivalence is uncertain, tests fail, or timing, failure paths or operational constraints need evidence. Load only the relevant reference, not both by default. Do not require another skill, a fixed model, delegation or a new tool before acting.

## Complete and stop

Make the smallest complete change within authorized scope. Migrate necessary consumers and remove genuinely retired machinery; a required compatibility layer is retained responsibility, not completed deletion. If completion would exceed scope, explain that boundary instead of leaving a broken half-migration.

Reuse valid evidence and run only checks that resolve actual uncertainty. Obvious semantic no-ops need no new test or model evaluation. Preserve unique behavioral protection; remove duplicate or explicitly retired expectations only when their remaining coverage is accounted for. Do not weaken an oracle to make the patch pass.

Stop when the useful simplification is complete or remaining edits are style churn, unsupported deletion, or not worth their risk and verification cost. Do not enforce a findings quota or repeated cleanup rounds. Distinguish no worthwhile change from a blocked or incompletely investigated candidate. Report the removed burden or clarity gain, decisive evidence, and material limits; audit-only work reports proposals, not completed changes.
