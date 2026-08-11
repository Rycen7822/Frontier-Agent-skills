# Fallback durable-work ledger

## Purpose

Provide one recoverable Markdown state only when cross-context recovery, destructive/external effects, staged migration or rollout, multiple authorized writers, or an explicit audit trail requires durability and neither host state nor an existing repository work item owns it.

## Admission boundary

Fallback uses one controller and one projection. Multiple writers first require a canonical Host or repository owner; without one, return the ownership blocker.

Normalize the objective by trimming it and collapsing every whitespace run to one ASCII space. Compute:

```text
TASK_KEY = first 12 lowercase hex characters of
           SHA256(UTF8(realpath(source_root) + "\n" + NORMALIZED_OBJECTIVE))
WORK_ROOT = source_root.parent / ".frontier-work" / TASK_KEY
LEDGER = WORK_ROOT / "workflow.md"
```

Compute `TASK_KEY` at admission and resume only to locate the same ledger. Keep it machine-side; source/state revisions and readable evidence own freshness, integrity, and correctness claims.

`WORK_ROOT` is outside the source root and contains `workflow.md` plus one `artifacts/` directory only when raw evidence lacks an existing Host/repository/tool owner. Keep one canonical copy of each retained artifact, with a readable name and ledger fields for media/schema, size, retention, named consumer, and one digest. Existing canonical artifacts remain with their owner. A non-directory root, unrecorded file, or root/objective mismatch returns a blocker with the existing bytes intact. Workers return results through the Host; the controller owns ledger edits.

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

Keep `Evidence and verification` as a compact index. Each durable claim row records claim/requirement ID, source/state revision, scope/coverage, producer, command or operation status, oracle/authority, freshness, limitations, changed/preserved facts, required recheck, and raw evidence refs. For a retained raw artifact, add its path, digest, size, media/schema, retention, and consumer. Set artifact count/byte ceilings at admission; reaching a ceiling preserves existing bytes and pauses new artifact creation until an explicit scope or retention disposition is available.

## Completion and cleanup

With no external consumer and only reproducible local evidence, mark `terminal-disposable`, verify delivery, and remove the exact work root. With a named handoff, audit, raw-evidence, or release consumer, mark `terminal-retain` until that consumer confirms use, then remove the exact root. Lifecycle and consumer disposition—not age—select cleanup, and one source/objective keeps one ledger.
