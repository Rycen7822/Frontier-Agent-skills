---
name: writing-plans
description: "Use after software decisions are settled to create a brief plan, executable handoff, migration plan, or resumable program."
license: MIT
metadata:
  version: 8.0.0
  author: Hermes Agent
  hosts: [codex, hermes-agent]
  hermes:
    tags: [planning, handoff, migration, documentation]
    category: software-development
    related_skills: [software-quality-workflows, long-document-segmented-writing]
---

# Writing Plans

Explicit invocation includes this full body; never reopen `SKILL.md`. Load non-Brief references directly without listing or counting files.

## Scope

Compile settled decisions into the lightest implementation-ready deliverable. Own intended state, order, authority, dependencies, recovery, and acceptance evidence. Do not rediscover intent, diagnose unknown causes, resolve architecture, execute, or claim verification.

Use only for an explicit plan request, cross-context handoff, or resumable migration/program. Routine same-session changes remain with `$software-quality-workflows`.

## Required inputs

Require a settled goal, non-goals, scope, authority, protected work, selected decisions, and acceptance evidence. Handoff and Program also require source freshness, authority, dependencies, rollback conditions, blockers, and an exact next action.

Do not invent missing facts. Return unresolved inputs to their owning workflow.

## Profiles

- **Brief**: one bounded outcome in the current context. Include goal, smallest change scope, ordered steps, verification, and only actual risks/rollback. Return it directly. When requested, write one Markdown file; never open a template or profile reference. Create no state.
- **Handoff**: work must cross a context boundary. Produce one canonical [Executable Handoff](templates/executable-handoff.md) and load [Handoff](references/profiles/handoff.md). Load exactly one of [Outcome slices](references/slicing/outcome-slices.md) or [Context capsules](references/slicing/context-capsules.md) only when independent outcomes, explicit dependency order, or a real target-context budget requires it.
- **Program**: a resumable multi-milestone program, migration, or rollout. Create and update one canonical [Program Plan](templates/program-plan.md), loading [Program](references/profiles/program.md). Load [Deprecation, migration, and rollout](references/migration/deprecation-and-rollout.md) only when a real migration or rollout exists.
- **Large source**: when the plan must carry source ranges, required sections, and a final document path, load only [Long-document handoff](references/bridges/long-document-handoff.md), then transfer explicitly to `$long-document-segmented-writing`. Load no other Writing Plans reference for that route.

Use the lightest profile that preserves continuation and proof. Brief loads no profile reference.

## Output rules

Produce one canonical deliverable, not a hidden state plus a projection. Handoff and Program remain single Markdown documents; update Program in place. A context capsule is a section inside that document and contains only current goal, essential source pointers, locked decisions, frontier, blockers, and exact next action.

Follow an explicitly requested JSON, YAML, or table format as the sole user deliverable. Create no sidecar, receipt, schema instance, renderer output, workflow root, or compatibility copy.

## Return unresolved work

Return unclear intent, unknown root cause, unresolved architecture, authority gaps, and feasibility work to `$software-quality-workflows`. SQW owns feasibility spikes through [Prototype lifecycle](../software-quality-workflows/references/workspace/prototype-lifecycle.md). Record the blocker and the exact missing decision; do not plan around guesses.

## Completion boundary

Planning is complete only when the chosen deliverable is internally consistent, source-bound where required, executable without rediscovery, and explicit about remaining blockers. This proves no implementation, test result, review verdict, release readiness, publication, deployment, or task completion.
