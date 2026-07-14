# Authority and Scope

Load this reference when the SQW entry's authority/scope guard fires: report/review coverage, dirty or concurrent work, delegation, external/persistent/destructive/privileged action, recovery, uncertain revision, or disputed scope/risk. It remains the single normative owner for request mode, authority precedence, risk classes, scope manifests, coverage, delegation roles, temporary resources, and side-effect escalation; the entry projects only its short universal kernel.

## Contents

- [Precedence](#precedence)
- [Request mode](#request-mode)
- [Risk classes](#risk-classes)
- [Scope manifest](#scope-manifest)
- [Coverage and revision freshness](#coverage-and-revision-freshness)
- [Dirty worktrees and ownership](#dirty-worktrees-and-ownership)
- [Delegation and roles](#delegation-and-roles)
- [Temporary resources and probes](#temporary-resources-and-probes)
- [External capability compatibility](#external-capability-compatibility)
- [Stop conditions](#stop-conditions)

## Precedence

Apply instructions in this order:

1. System and developer instructions.
2. The closest applicable project instructions, including `AGENTS.md`.
3. The user's request and any plan the user approved or explicitly requested to execute.
4. This umbrella authority contract.
5. The selected domain reference.
6. Examples and recipes.

A lower layer cannot widen the authority granted by a higher layer. Capability does not imply permission.

## Request mode

Classify the request before choosing tools or references.

| Mode | Typical verbs | Default result | Local edits |
|---|---|---|---|
| `report` | review, audit, inspect, explain, assess, summarize | Findings, evidence, recommendations, or status | Prohibited unless the user later requests a change |
| `diagnose` | why, reproduce, investigate, localize, determine cause | Reproduction, supported root cause, and residual uncertainty | Prohibited; temporary external probes are allowed only within the risk rules below |
| `change` | fix, implement, refactor, simplify, update, migrate | Scoped edits plus proportionate proof | Allowed only inside the authorized scope |

When one request says both review and fix, run two explicit phases: report first, then change only the findings and paths the user authorized. A dry run is an option within `change`; it is not the protection for report-only intent.

## Risk classes

| Risk class | Examples | Default policy |
|---|---|---|
| `READ_ONLY` | Bounded reads/searches, diffs, status, existing logs/results, local metadata queries, and checks proven not to write state | Allowed inside the requested scope |
| `LOCAL_REVERSIBLE` | Allowlisted edits, task-unique temporary directories, scoped test/build processes, caches, and disposable fixtures or stores | Allowed in `change`; in `report` or `diagnose`, only as a task-owned disposable verification/diagnostic probe with known isolation and cleanup and no product, user, or external-state mutation |
| `EXTERNAL_STATE` | Push, hosted review comments or approvals, CI reruns, remote writes, releases, installed-copy synchronization, persistent service changes | Require the user request or an already approved workflow to include that exact class of action |
| `PRIVILEGED_DANGEROUS` | Host policy changes, real-data deletion, destructive version-control operations, unknown-process attach or signals, publicly reachable debuggers | Explain the risk and safer alternative, then obtain explicit authorization for the exact action |

Ordinary permission to fix code does not include external publication, approval, installation, persistent services, host policy changes, or real-data deletion. Prefer a lower-risk alternative whenever it can answer the same question.

Classify a command by its actual side effects, not by names such as `test`, `check`, `build`, or `dry-run`. Tests and checks may write caches, generated files, fixture databases, snapshots, ports, processes, or network records. Inspect the owning configuration or isolate the run in a task-owned disposable state; upgrade the risk class whenever persistent, shared, privileged, or external effects remain possible.

## Scope manifest

M0 does not create a durable manifest by default. Keep the smallest in-session record that preserves the contract:

```text
workflow_mode: M0_DIRECT
request_mode: report | diagnose | change
allowed: one owner/path seam
protected: unrelated work
source: current checkout or explicit unversioned state
allowed_side_effects: local reversible ceiling
proof: focused check plus proportional affected gate
```

Persist the full manifest for report/review coverage, M2/M3, delegation, dirty/concurrent work, uncertain revision, broad diagnosis/change, or when scope must survive a handoff:

```text
workflow_mode: M1_TRACE | M2_SPARSE | M3_FULL
request_mode: report | diagnose | change
root: logical repository or artifact root
base_revision: revision, snapshot, or not_applicable
head_revision: revision, snapshot, or not_applicable
paths:
  - path: logical/path
    status: added | modified | deleted | renamed | untracked | unchanged
    snapshot_id: immutable content, diff/base, deletion, rename, or artifact identifier
generated_vendor_binary: classification and reason
requested_exclusions: explicit list
scope_hash: stable digest or equivalent snapshot identifier
allowed_side_effects: highest authorized risk class and any narrower allowlist
```

Use one manifest for diff selection, scans, test selection, reviewer slices, fixes, and final reporting. Compute `scope_hash` from the canonical manifest, including per-path snapshot identifiers. Re-observe both the current head and current scope hash at review/fix boundaries so same-HEAD dirty or untracked drift cannot be hidden. Do not silently switch among staged changes, an arbitrary recent commit, the full worktree, or a hosted change request.

Prefer an existing repository-defined manifest digest. Otherwise normalize root-relative paths to POSIX form, sort path records by path and object keys deterministically, omit volatile timestamps, serialize the declared manifest as UTF-8 JSON with stable separators, and hash those bytes with SHA-256. Derive each `snapshot_id` from immutable content, diff/base, deletion, rename, or artifact evidence rather than modification time alone; use the same procedure for the later current-scope observation.

Generated, documentation, configuration, binary, and vendor items are not automatically out of scope. Classify their review depth and record the reason. A deleted path is reviewed from the diff or base snapshot rather than read as if it still exists.

## Coverage and revision freshness

For a large scope, maintain a coverage ledger with each path's snapshot identifier and one status:

- `full`: the relevant diff and owning context were reviewed.
- `sampled`: only a declared portion was reviewed; record the sampling boundary.
- `not_reviewed`: the item could not be covered.

Any unread or truncated material makes coverage partial. A scan match begins as `scan_candidate`; it becomes a finding only after contextual review.

Bind findings and fixes to the reviewed head revision. If the source revision changes, re-read affected paths and rerun relevant proof. A stale result cannot authorize publication or approval.

## Dirty worktrees and ownership

- Treat existing tracked, untracked, ignored, generated, and scratch content as potentially user-owned.
- Preserve unrelated changes and concurrent-agent work. Do not restore, discard, stage, move, or clean a path merely because it looks temporary.
- Derive every edit, staging action, or cleanup path from the manifest allowlist.
- For an existing patch, capture characterization or regression evidence; do not delete implementation to recreate an ideal development history.
- Clean only artifacts created by this task whose ownership is certain, and verify the remaining state afterward.

## Delegation and roles

Whether delegation is allowed comes from the active host instructions, not a nested recipe. When allowed, choose the smallest useful fan-out based on independent risk surfaces, available slots, latency, and cost.

| Role | Authority |
|---|---|
| Reviewer | Read-only; returns structured findings and coverage |
| Fixer | May edit only allowlisted paths for `code_fixable=true` findings; cannot approve its own work |
| Publisher | May perform external writes only when that action is explicitly authorized |
| Controller | Validates scope, schema, freshness, edits, and proof before making the final claim |

If independent agents are unavailable or prohibited, perform a fresh-context local pass and report that independent separation-of-duties evidence was not obtained. Do not make quality completion permanently depend on a tool the current host does not provide.

## Temporary resources and probes

- Use a task-unique temporary directory and record its owner and path.
- Before extracting an artifact, reject absolute paths, parent traversal, and unsafe links; assert the expected candidate count and identity.
- Prefer read-only probes. For network, build, GPU, remote SDK, database, or persistent-runtime probes, state credentials, cost, retry budget, data residue, and cleanup before execution.
- Keep probe data disposable and scoped. Never share a fixed temporary path across concurrent tasks.
- Classify failures as product failure, harness gap, environment unavailable, or permission denied before changing product behavior.

## External capability compatibility

Select an external skill or connector as the single owner only after confirming that it is available and compatible with this request's mode, risk ceiling, project rules, revision model, and required proof. If compatibility cannot be established, use the registered local safe fallback and name the evidence gap.

Never weaken a gate merely because a specialized capability is absent. A platform-specific fallback is read-only unless the user separately authorized platform writes.

## Stop conditions

Stop and request direction when:

- the next step exceeds the authorized risk class;
- the scope or source revision cannot be determined safely;
- a requested action would overwrite unrelated work;
- a privileged, destructive, external, financial, or persistent side effect is necessary and not already authorized;
- evidence shows the requested technical route is materially unsound and no in-scope safe alternative exists.

Otherwise make the best-supported safe choice and continue without routine approval questions.
