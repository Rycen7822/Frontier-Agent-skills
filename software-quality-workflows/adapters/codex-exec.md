# Codex Exec Adapter

This adapter binds a frozen autonomous-closure task to the installed `codex exec` CLI. It is a platform adapter, not a lifecycle or transition owner. It never turns model output into canonical workflow state: `scripts/advance_closure.py` remains the only closure phase mutation API.

## Admission and capability probe

Live execution is default-off. Before creating a task, call `probe_codex_capabilities()` from `scripts/local_workflow_adapter.py`. The capability probe runs only `codex --help` and `codex exec --help`; it does not start a model. Root and exec help are checked separately because installed versions may expose approval policy only as a root option. A task is eligible only when the installed CLI exposes JSONL output, output-schema, last-message, sandbox, approval, working-directory, and resume capabilities. Missing capabilities produce a structured environment blocker and never trigger an improvised command.

The controller must also bind the task to the current source revision, frozen contract hash and epoch, plan hash, policy bundle hash, scope, candidate worktree, and hard timeout. Network is disabled unless the frozen contract names an allowlist of domains and the relevant data boundary. Remote writes are outside the P4 publication ceiling.

## Task envelope

Every invocation uses the machine-checked envelope described in the closure contract. In addition to the objective and role, it records:

- task and run IDs;
- an already-created candidate worktree below `.closure/worktrees/`;
- source, contract, plan, and policy bindings;
- constraint and counterexample references;
- allowed writes and protected paths;
- required outputs, forbidden actions, and typed stop conditions;
- `workspace-write` sandbox, explicit network policy, and timeout.

Candidate workers are always forbidden from publication, contract changes, verifier-kernel changes, promotion, and closure. Reviewers are read-only. The controller validates the envelope before starting a process; invalid scope or stale bindings produce no invocation.

## Non-interactive invocation

After a successful capability probe, the controller may assemble the installed-version-compatible equivalent of:

```text
codex --ask-for-approval never exec --json \
  --output-schema .closure/schemas/codex-task-result.schema.json \
  --output-last-message "$RESULT_JSON" \
  --sandbox workspace-write \
  -C "$WORKTREE" - < "$TASK_PROMPT" \
  > "$EVENTS_JSONL" 2> "$PROGRESS_LOG"
```

The controller reserves three distinct controller-owned paths before launch and records only bounded regular files after exit. `EVENTS_JSONL` is an immutable diagnostic artifact; when present, `RESULT_JSON` is parsed with duplicate-key, size, depth, and non-finite-number protections before schema validation. Progress logs are diagnostic only and follow the frozen evidence redaction policy.

The approval setting is valid only with the frozen least-privilege sandbox. It does not widen task authority. The session records the observed termination and exit code. If a nonzero exit occurs before `RESULT_JSON` exists, `record_codex_execution_failure()` may synthesize one controller-authored, schema-validated certificate only after proving that the candidate worktree is unchanged. Capacity, authentication, timeout, cancellation, and unclassified execution failures map to distinct `E_AGENT_*` codes; they never publish a candidate. Timeout and cancellation certificates are non-retryable unless a later controller policy explicitly creates a new task.

## Result and controller handoff

`schemas/codex-task-result.schema.json` accepts only `completed`, `blocked`, or `failed` results. A completed candidate must identify its exact candidate artifact. Blocked and failed results must carry a structured blocker. Changed paths are checked against both allowed writes and protected surfaces.

Allowed result events are proposals such as `candidate_generated`, `counterexample_observed`, and `verification_requested`. Promotion, sign-off, terminal closure, and publication are not valid model outputs. After validating result schema, task identity, path scope, worktree snapshot, patch/tree hashes, and referenced artifacts, the controller translates an accepted proposal into a new event and calls `scripts/advance_closure.py`. Rejected proposals remain diagnostic artifacts.

## Session and resume binding

For each invocation, retain a controller-owned session record with task ID, session/thread ID, source revision, contract hash and epoch, plan hash, policy bundle hash, command capability fingerprint, paths to JSONL/result/progress artifacts, and—when the process has exited—its termination and exit code. A successful or legacy session requires a result file. A failed, timed-out, or cancelled session may omit it, but still requires safe JSONL and progress files. Resume is allowed only when all task/source/contract/plan/policy bindings are byte-for-byte identical. Any mismatch creates a new task; it does not resume an older session.

Subagents inherit the same or narrower sandbox and path scope. They cannot receive controller secrets, hidden holdouts, credentials, or a broader write set. Disable parallel work whenever worktrees, resource locks, oracle comparability, or cost budgets are not proven independent.

## Worktree lifecycle and retention

The local filesystem adapter creates the candidate worktree from the frozen base, records controller-owned metadata, and later computes the patch hash, tree hash, changed paths, and protected-surface diff. Candidate output is archived content-addressably before removal. Integration uses a clean worktree and reruns the affected cascade plus all four sign-off axes. A worker worktree is never promoted in place.

Git command failure yields an artifact/event proposal and does not modify canonical state. Cleanup is permitted only below the configured `.closure/worktrees/` root, after archive verification, and without remote operations. Session records, result JSON, candidate manifest, patch, evaluations, counterexamples, and sign-off evidence follow the frozen retention policy.

## Error mapping

- missing CLI capability, executable, or required environment → `ENVIRONMENT_UNAVAILABLE`;
- task/result schema failure → `E_SCHEMA_INVALID`;
- stale session or hash binding → `E_ARTIFACT_STALE`;
- path outside allowed writes → `E_SCOPE_VIOLATION`;
- protected path change → `E_PROTECTED_SURFACE_CHANGED`;
- worker promotion/close/publication request → `E_UNAUTHORIZED_TRANSITION` or `E_PUBLICATION_CEILING`;
- writer/worktree lock conflict → `E_LOCK_CONFLICT`;
- pre-result usage/quota exhaustion → `E_AGENT_CAPACITY`;
- pre-result authentication failure → `E_AGENT_AUTH`;
- pre-result timeout/cancellation → `E_AGENT_TIMEOUT` / `E_AGENT_CANCELLED`;
- another pre-result nonzero exit → `E_AGENT_EXECUTION_FAILED`;
- any partial worktree mutation on this mapping path → `E_UNBOUND_AGENT_CHANGES` and no synthesized task result.

These are proposals or adapter failures. Only the deterministic controller can decide the next phase or emit a terminal certificate.
