# Fallback durable-work ledger

## Purpose

Provide one recoverable Markdown state only when cross-context recovery, destructive/external effects, staged migration or rollout, multiple authorized writers, or an explicit audit trail requires durability and neither host state nor an existing repository work item owns it.

## Admission boundary

Fallback is allowed only with one controller. If coordination has multiple writers and no canonical host or repository owner, stop with a blocker. Do not add a lease, lock, daemon, event stream, registry, compatibility reader, or second projection.

Normalize the objective by trimming it and collapsing every whitespace run to one ASCII space. Compute:

```text
TASK_KEY = first 12 lowercase hex characters of
           SHA256(UTF8(realpath(source_root) + "\n" + NORMALIZED_OBJECTIVE))
WORK_ROOT = source_root.parent / ".frontier-work" / TASK_KEY
LEDGER = WORK_ROOT / "workflow.md"
```

`WORK_ROOT` must be outside the source root. Create only that directory and `workflow.md`. If the path is not a regular directory, contains another file, or the recorded identity differs, stop without overwriting, deleting, or choosing a hidden alternate root. Workers return results through the host and never edit the ledger.

## Required document

```markdown
# Workflow State

## Identity and objective
## Authority, scope, and protected work
## Current stage and source freshness
## Decisions and invariants
## Evidence and verification
## Test disposition
## Next action and blockers
## Completion and cleanup
```

Record the canonical source root, normalized objective, initial source identity, controller, creation time, and lifecycle `active|terminal-retain|terminal-disposable`. On every recovery, re-observe revision and dirty/concurrent state, record drift, and re-establish scope, decisions, and evidence freshness before continuing.

## Completion and cleanup

With no external consumer, mark `terminal-disposable`, verify delivery, and remove only the exact work root. With a named handoff, audit, or evidence consumer, mark `terminal-retain` until that consumer confirms use, then remove it. Never delete by age, scan globally, or start a second ledger for the same source/objective while a retained ledger is unconsumed.

Do not scan, read, migrate, delete, import, alias, or dual-write any v4 owner root, anchor, protocol artifact, or state. Finish an active v4 task in v4, or terminate it explicitly and restart from current repository truth.
