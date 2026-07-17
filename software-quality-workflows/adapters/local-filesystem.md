# Local Filesystem Adapter

This is the P1, skill-only adapter for M2 Sparse and M3 Full. M0 never creates it; M1 uses only an explicitly task-owned trace path. The caller chooses a project-approved worknote/temp root or an external task-owned directory. The adapter never runs `git add` or expands authority.

Layout:

```text
.workflow/
  state.json
  events.jsonl
  locks.json
  artifacts/
  capsules/
  worktrees/
  worktree-metadata/
  README.md
```

`scripts/local_workflow_adapter.py` validates state/event schemas before writes, uses compare-and-swap `state_version`, writes a same-directory temp file, flushes and `fsync`s it, then uses atomic replace and directory sync. Event append is logically append-only but P1 rewrites the validated bounded JSONL file atomically so a crash cannot expose a truncated last record.

Adapter mutation uses a process-scoped host file lock, so a crashed process releases mutual exclusion without requiring deletion of a stale sentinel. `locks.json` is the local canonical lease projection and is merged into effective state before resume checks. An expired resource lock must be reconciled before reuse; it is never silently stolen. Content-addressed artifacts reject raw credentials and all payloads classified sensitive; sensitive data stays at an external controlled pointer. Crash leftovers remain discoverable as orphan artifacts until the controller reconciles them; cleanup is separate and task-owned.

Resume validates source revision, scope hash, plan hash, event ordering, artifact hashes, pending background work, and leases. A drift report may select local repair or require parent replan; it never rewrites plan decisions.

CLI examples use explicit paths:

```text
python3 scripts/local_workflow_adapter.py /task/.workflow init /task/initial-state.json
python3 scripts/local_workflow_adapter.py /task/.workflow commit /task/next-state.json --expected-version 3
python3 scripts/local_workflow_adapter.py /task/.workflow append-event /task/event.json --expected-sequence 4
python3 scripts/local_workflow_adapter.py /task/.workflow resume
```

These commands only update the named task-owned workflow directory. Commit here means state compare-and-swap, not a VCS commit.
