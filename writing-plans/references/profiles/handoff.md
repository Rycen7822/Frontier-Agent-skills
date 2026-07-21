# Executable Handoff Profile

## Purpose

Make one cross-context software handoff executable without repeating intent discovery or architecture selection.

## Use when

Use after goal, decisions, authority, scope, and acceptance evidence are settled, but another context, session, or engineer must execute the work.

## Inputs

- Exact source revision and freshness condition.
- Goal, non-goals, protected work, allowed writes, and allowed effects.
- Locked decisions and invariants with source pointers.
- Ordered work, dependencies, verification, rollback, blockers, and exact next action.

## Required result

Write one canonical Markdown using the [Executable Handoff template](../../templates/executable-handoff.md). Every slice names an observable outcome, owned paths or seams, prerequisites, acceptance evidence, and rollback when real. Point to source evidence instead of copying large excerpts.

The receiver rechecks revision, dirty state, authority, and external effects before executing. The handoff records authority; it does not grant it.

## Failure boundary

Return to Software Quality Workflows when intent, root cause, architecture, authority, or feasibility is unresolved. Stop if source freshness or protected work cannot be stated exactly. Create no second plan, sidecar, state, or generated summary.
