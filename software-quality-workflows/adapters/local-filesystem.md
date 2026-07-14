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

Adapter mutation uses a process-scoped host file lock, so a crashed process releases mutual exclusion without requiring deletion of a stale sentinel. `locks.json` is the local canonical lease projection and is merged into effective state before frontier/resume checks. An expired resource lock must be reconciled before reuse; it is never silently stolen. Content-addressed artifacts reject raw credentials and all payloads classified sensitive; sensitive data stays at an external controlled pointer. Crash leftovers remain discoverable as orphan artifacts until the controller reconciles them; cleanup is separate and task-owned.

For `autonomous_closure`, the same adapter is also the bounded Git worktree manager. `create_candidate_worktree`, `inspect_candidate_snapshot`, `archive_candidate`, `remove_candidate_worktree`, and `create_integration_worktree` are controller operations, not a scheduler. They require the exact frozen/observed commit, a clean explicit base snapshot, a task-owned root inside that repository, and safe relative scope patterns. Repository hooks, global/system Git configuration, fsmonitor, pagers, and active checkout filters are disabled or rejected before checkout. No operation invokes a remote Git command.

Each candidate is detached at the frozen base and has one immutable controller metadata record. `.closure-view/` is a read-only projection whose hashes are rechecked at inspection. Snapshot identity binds tracked patch bytes, untracked contents, base tree, changed paths, modes, tree hash, scope violations, protected-surface changes, unsafe symlinks, and secret-shaped data. A candidate can be removed only after an adapter-generated content-addressed archive is reloaded, strictly decoded, matched to the current snapshot, and found in the immutable controller archive record. Integration worktrees are created cleanly from the same base; candidate worktrees are never promoted in place.

All worktree mutations hold the adapter process lock and return only artifact/event proposals. Git failure, stale source, unsafe configuration, snapshot drift, or archive mismatch does not update `state.json` or `events.jsonl`. Closure state/event mutation remains exclusively owned by `scripts/advance_closure.py`; direct local-adapter commit and append paths are not closure transition APIs.

Resume validates source revision, scope hash, plan hash, event ordering, artifact hashes, pending background work, and leases. A drift report may select local repair or require parent replan; it never rewrites plan decisions.

CLI examples use explicit paths:

```text
python3 scripts/local_workflow_adapter.py /task/.workflow init /task/initial-state.json
python3 scripts/local_workflow_adapter.py /task/.workflow commit /task/next-state.json --expected-version 3
python3 scripts/local_workflow_adapter.py /task/.workflow append-event /task/event.json --expected-sequence 4
python3 scripts/local_workflow_adapter.py /task/.workflow resume
```

These commands only update the named task-owned workflow directory. Commit here means state compare-and-swap, not a VCS commit.
