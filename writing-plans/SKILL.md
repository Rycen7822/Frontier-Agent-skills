---
name: writing-plans
description: "Create executable handoffs, migration plans, or resumable programs after decisions."
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

## Scope

Compile settled decisions into one source-bound Markdown plan. Use Handoff when execution crosses a context; use Program only when a multi-milestone frontier changes across contexts. Same-session planning stays model-native.

Do not brainstorm intent, diagnose causes, select architecture, implement, run verification, or claim completion.

## Source binding

Before planning, read only user-named sources, minimum owner files for the first source-changing slice, `HEAD` and `git status --short` only for cross-session freshness, and the existing plan only when updating a Program. Never inspect skill/package internals or sizes, Git authors/refs/objects, unrelated repository inventory, or files used only to fill a format.

Every plan binds:

- Source root:
- Revision or explicit non-Git source identity:
- Relevant dirty/protected paths:
- First-slice owner files/symbols:

## Settled and unresolved

Treat user-stated goal, non-goals, first slice, target files, authority, acceptance evidence, and observed source facts as settled; never invent current facts.

Unknown later rollout, telemetry, ownership, or deprecation facts block only dependent milestones, not an authorized local first slice. Missing outcome-changing intent, current write authority, or irreversible approval blocks the affected slice. Record and return the blocker to the caller or owner; do not hard-code another skill dependency.

## Inline contracts

A Handoff contains:

- Goal / non-goals:
- Bound source identity:
- Protected work and allowed effects:
- Settled decisions:
- First source-changing slice:
- Files/symbols to change:
- Acceptance and verification:
- Rollback/cleanup when material:
- Later blockers and dependencies:
- Resume preflight:
- Exact next source-changing action:

A Program contains every Handoff field plus:

- Milestones in dependency order:
- Current frontier:
- Per-milestone acceptance:
- Migration/deprecation owner and removal condition when applicable:
- Update-in-place rule:

Multiple steps alone do not create a Program; the frontier must change across contexts.

## Preflight and first change

`Resume preflight` checks revision, relevant dirty/protected paths, and freshness. `Exact next source-changing action` names the first file or symbol to modify afterward and its expected behavior. It cannot be inspection, reading, ownership confirmation, or requirement collection unless the plan is blocked with no authorized source-changing slice.

## Output boundary

For a reply task, the final answer is the only plan. For a file task, create or update only the user-named Markdown file; update a Program in place. Create no `PHASE0.md`, sidecar, receipt, state, schema instance, renderer output, or compatibility copy.

Break Markdown lines only at paragraph, list-item, quote, or structural boundaries; never hard-wrap a sentence to terminal width. Do not implement source. Planning completion proves only that the single plan is consistent, source-bound, executable without rediscovery, and honest about blockers—not that implementation, verification, review, release, publication, or deployment occurred.
