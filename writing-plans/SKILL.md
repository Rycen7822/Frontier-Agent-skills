---
name: writing-plans
description: "Create brief plans, handoffs, migration plans, or resumable programs after decisions."
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

Explicit invocation is this full body. Never reopen `SKILL.md`, inventory workspace/skill/Git internals, or size references; read only named non-Brief files.

## Scope

Compile settled decisions into the lightest executable deliverable with order, authority, dependencies, recovery, and acceptance evidence. Never rediscover intent, diagnose causes, resolve architecture, execute, or claim verification.

Use for explicit planning, handoff, or resumable migration/program. Routine same-session changes stay with `$software-quality-workflows`.

## Required inputs

Require settled goal/non-goals, scope, authority, protected work, decisions, and acceptance evidence. Handoff/Program also require source freshness, dependencies, rollback, blockers, and exact next action.

Never invent facts; return unresolved inputs to their owner.

## Profiles

- **Brief**: one bounded outcome in the current context with no owner/session/migration/release transition. State goal, steps, verification, and real risk/rollback. Return directly or write one requested Markdown file; never open a template or profile reference or create state. Brief loads no profile reference.
- **Handoff**: one transfer must cross a context boundary: owner, session, environment, staged migration, or release; no ongoing program state. Produce one [Executable Handoff](templates/executable-handoff.md) and load [Handoff](references/profiles/handoff.md). Load exactly one of [Outcome slices](references/slicing/outcome-slices.md) or [Context capsules](references/slicing/context-capsules.md) only for independent outcomes, dependency order, or a proven context budget.
- **Program**: a resumable multi-milestone effort with a changing frontier; never select it merely because one handoff has ordered migration/rollout stages. Create/update one [Program Plan](templates/program-plan.md), load [Program](references/profiles/program.md), and load [Deprecation and rollout](references/migration/deprecation-and-rollout.md) only for a real migration/rollout.
- **Large source**: when carrying source ranges, sections, and final path, load only [Long-document handoff](references/bridges/long-document-handoff.md), transfer to `$long-document-segmented-writing`, and load no other Writing Plans reference.

Use the lightest profile preserving continuation and proof.

## Output rules

Produce one canonical deliverable, not hidden state plus a projection. Handoff and Program are single Markdown documents; update Program in place. A context capsule is one section containing only goal, source pointers, locked decisions, frontier, blockers, and exact next action.

Every profile states non-goals, allowed writes/effects, and an exact next action.

Place every unresolved prerequisite before dependent slices, make its resolution the exact next action, and mark the dependent work blocked.

Use any requested JSON, YAML, or table as the sole deliverable. Create no sidecar, receipt, schema instance, renderer output, workflow root, or compatibility copy.

## Return unresolved work

Return unclear intent, unknown root cause, unresolved architecture, authority gaps, and feasibility to `$software-quality-workflows`. SQW owns feasibility spikes through [Prototype lifecycle](../software-quality-workflows/references/workspace/prototype-lifecycle.md). Record the blocker and missing decision; never plan around guesses.

## Completion boundary

Planning is complete when the deliverable is consistent, source-bound where required, executable without rediscovery, and explicit about blockers. This proves no implementation, test, review, release readiness, publication, deployment, or task completion.
