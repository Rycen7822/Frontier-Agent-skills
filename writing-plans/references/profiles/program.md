# Program Profile

## Purpose

Maintain one resumable plan for a multi-milestone software program whose dependencies, migration, or rollout cannot be represented safely as a Brief or one-way handoff.

## Use when

Use only after goal, architecture, authority, and acceptance strategy are settled and the work has multiple dependent milestones, a changing frontier, or a real migration/rollout boundary.

## Inputs

- Source identity, scope, authority, outcomes, non-goals, decisions, and invariants.
- Each Phase or milestone with dependencies and independently observable proof.
- Current frontier, blockers, rollback, and exact next executable slice.
- Temporary compatibility owner and removal contract when compatibility is unavoidable.

## Required result

Create one canonical Markdown from the [Program Plan template](../../templates/program-plan.md) and update it in place. Keep completed history compressed to current facts. `Decision lineage` records only a current decision and the decision it replaced in one line.

Each Phase or milestone describes outcomes rather than horizontal implementation layers. Proof gates name observable evidence without claiming it has run.

## Failure boundary

Return unresolved intent, cause, architecture, authority, or feasibility to Software Quality Workflows. Stop if the current frontier or next executable slice cannot be identified. Do not create plan state, timeline logs, projections, or sidecars.
