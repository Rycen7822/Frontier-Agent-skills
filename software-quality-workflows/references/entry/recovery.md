---
{
  "card_id": "sqw.entry.recovery",
  "card_version": 1,
  "kind": "entry",
  "consumes": [
    "repository_state",
    "operation_state",
    "authority_projection"
  ],
  "produces": [
    "recovery_route",
    "protected_state"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 4096,
  "neighbors": [
    {
      "edge_id": "recovery-to-merge-state",
      "to_card_id": "sqw.recovery.merge-state-and-sides",
      "edge_mode": "hard",
      "hard_predicate_id": "merge-conflict-active",
      "missing_decision": "Active merge operation and sides are not identified",
      "required_evidence": "Git operation state and base/ours/theirs evidence",
      "evict_when": "Merge state and sides are recorded"
    },
    {
      "edge_id": "recovery-to-repository",
      "to_card_id": "sqw.recovery.repository-recovery",
      "edge_mode": "hard",
      "hard_predicate_id": "repository-state-unsafe",
      "missing_decision": "Repository state is damaged or incomplete",
      "required_evidence": "Index, refs, worktree, and operation evidence",
      "evict_when": "Repository recovery result is recorded"
    },
    {
      "edge_id": "recovery-to-cleanup",
      "to_card_id": "sqw.recovery.cleanup",
      "edge_mode": "hard",
      "hard_predicate_id": "cleanup-authorized",
      "missing_decision": "Authorized cleanup set and retention proof are unresolved",
      "required_evidence": "Explicit cleanup authority and object inventory",
      "evict_when": "Cleanup result and retained state are verified"
    }
  ]
}
---
# Recovery Entry

## Decision this card owns
Select the one recovery owner that matches observed repository state without performing destructive cleanup by default.

## Use when
- A merge operation, index/ref/worktree fault, interrupted operation, or explicitly authorized cleanup blocks normal work.

## Do not use when
- The repository is healthy and only product behavior is failing.

## Required inputs
- Repository status, active operation markers, source identity, protected paths, and exact cleanup authority.

## Procedure
1. Observe repository and operation state without changing it.
2. Identify protected, dirty, untracked, generated, and task-owned paths.
3. Distinguish merge intent from repository damage and optional cleanup.
4. Preserve all state not explicitly owned by this recovery.
5. Select exactly one matching recovery edge.
6. Emit a typed blocker when state or authority is insufficient.

## Output contract
- `recovery_kind`, `protected_state`, `selected_edge_id|null`, `required_evidence`, and `blocker|null`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `recovery-to-merge-state` | Active merge operation and sides are not identified | Git operation state and base/ours/theirs evidence | `sqw.recovery.merge-state-and-sides` | Merge state and sides are recorded |
| `recovery-to-repository` | Repository state is damaged or incomplete | Index, refs, worktree, and operation evidence | `sqw.recovery.repository-recovery` | Repository recovery result is recorded |
| `recovery-to-cleanup` | Authorized cleanup set and retention proof are unresolved | Explicit cleanup authority and object inventory | `sqw.recovery.cleanup` | Cleanup result and retained state are verified |

## Stop
Stop after selecting one recovery path or emitting an authority/state blocker.
