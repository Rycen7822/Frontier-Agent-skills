# Fallback durable-work ledger

## Purpose

Provide one recoverable Markdown state only when cross-context recovery, destructive/external effects, staged migration or rollout, multiple authorized writers, or an explicit audit trail requires durability and neither host state nor an existing repository work item owns it.

## Admission boundary

Use existing Host state, repository work items, or the project worklog first. Fallback uses one writer and one Markdown projection only when no existing state owner can preserve the required continuity. Multiple writers first require a canonical Host or repository location; without one, return the coordination blocker.

Choose a task-specific work root from an existing project convention, an explicit user path, or a unique temporary path outside shipped source. Use a readable task name; do not derive a directory identity from source, objective, command, or output hashes and do not create a registry solely to locate the ledger.

```text
WORK_ROOT = <existing project work root or unique task-owned temporary root>
LEDGER = WORK_ROOT / "workflow.md"
```

`WORK_ROOT` contains `workflow.md` plus one `artifacts/` directory only when non-replayable raw evidence lacks an existing Host, repository, or tool owner. Keep one canonical copy of each retained artifact with a readable name, retention, and named consumer. Use one digest only when named external or non-replayable bytes cross a real boundary; never hash commands or outputs merely to identify retries. Existing canonical artifacts remain with their owner. A non-directory root, unrecorded file, or objective mismatch returns a blocker with the existing bytes intact. Workers return results through the Host; the single admitted writer owns ledger edits.

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

Record the source root, objective, current stage, single writer, creation time, and lifecycle `active|terminal-retain|terminal-disposable`. Record a source revision only when a durable claim depends on it. On recovery, re-observe relevant source and dirty/concurrent state, record material drift, and re-establish scope, decisions, and evidence freshness before continuing.

Keep `Evidence and verification` as a compact index. For a failure that needs continuity, record `Failure`, `Class`, the literal command or stable operation name, decisive error text or log path, and `Decision`. Durable claims add only the source/state fact, scope/coverage, producer, operation status, oracle, freshness, limitations, required recheck, and raw evidence refs that a later reader needs. For retained raw artifacts, add path, size, media/schema, retention, consumer, and a digest only when the bytes cross the named boundary. Set artifact count/byte ceilings at admission; reaching a ceiling preserves existing bytes and pauses new artifact creation until an explicit scope or retention disposition is available.

## Completion and cleanup

With no external consumer and only reproducible local evidence, mark `terminal-disposable`, verify delivery, and remove the exact work root. With a named handoff, audit, raw-evidence, or release consumer, mark `terminal-retain` until that consumer confirms use, then remove the exact root. Lifecycle and consumer disposition—not age—select cleanup, and one source/objective keeps one ledger.
