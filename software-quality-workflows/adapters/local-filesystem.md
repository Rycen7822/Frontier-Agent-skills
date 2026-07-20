# Local Filesystem Adapter

This adapter is the single durable owner for M2 Sparse and M3 Full workflows. M0 creates no control root, and M1 is rejected. The caller creates an empty task-owned work root outside the source root before invoking `scripts/card_cycle.py`; the CLI never creates that root, edits source files, runs Git writes, or expands authority.

The established owner surface is fixed:

```text
<work-root>/
  .adapter.lock
  state.json
  locks.json
  artifacts/
  projections/
```

`events.jsonl` appears only after an operator appends audit evidence. The only permitted transient siblings are `.state.json.tmp`, `.locks.json.tmp`, `.events.jsonl.tmp`, and `projections/workflow-context.md.tmp` in their defined recovery states. No README, initialization marker, capsule tree, worktree metadata, or second ledger belongs to this owner.

`.adapter.lock` is an immutable owner header created during bootstrap and opened without creation for every established operation. `state.json` is canonical semantic truth; its compare-and-swap key is exactly `state_version` plus `state_hash`. `locks.json` contains bounded card leases and is not merged into state or state hashing. `events.jsonl` is an optional bounded operator audit stream and never makes a semantic receipt stale.

M2/M3 bootstrap publishes the fixed surface in the order lock, prepared state, `locks.json`, `artifacts/`, `projections/`, committed state, and first lease. Ordinary card completion publishes any immutable materialized artifact before the state reference, commits semantic state, then converges the next-lease projection. Fixed sibling temps, atomic replace, file and directory syncs, and exact owner headers make every legal interrupted prefix replayable; foreign, partial, stale, linked, or out-of-scope entries fail closed and remain unchanged.

`route resume` validates the owner locator, bundle contract, scope binding, current source snapshot, source root binding, repository HEAD/tree when applicable, prepared operation, projection surface, and lease owner. Eligible changes limited to the immutable `allowed_writes` set produce a pending source transition. Revision, root, source-kind, HEAD/tree, exterior, or out-of-scope drift returns a blocked locator and no next lease.

Repository capture uses one fixed local-config preflight, one canonical top-level check, and two observations of `HEAD^{commit}`/`HEAD^{tree}`, the full staged index, and porcelain-v2 status. Git children receive a fixed empty-derived environment with remote prompting, global/system configuration, hooks, filters, diff commands, lazy fetch, unsafe index flags, and weakened status semantics disabled or rejected. Both pipes are drained to EOF under one deadline; non-empty stderr, caps, timeout, unsafe paths, or raw-byte drift fail before owner mutation.

The model-facing lifecycle uses canonical JSON on stdin and receipts on stdout:

```text
python3 scripts/card_cycle.py route    --input - --source-root /task/source [--work-root /task/workflow]
python3 scripts/card_cycle.py complete --input - --source-root /task/source [--work-root /task/workflow]
python3 scripts/card_cycle.py render   --input - --source-root /task/source --work-root /task/workflow
```

The adapter module exposes no independent state, lease, artifact, initialization, commit, or resume CLI. Its only standalone command is the operator audit append:

```text
python3 scripts/local_workflow_adapter.py /task/workflow append-event /task/event.json --expected-sequence 4
```
