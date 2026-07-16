---
{
  "card_id": "sqw.recovery.merge-state-and-sides",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "git_operation_state",
    "conflict_inventory",
    "source_identity"
  ],
  "produces": [
    "merge_state_record",
    "side_identity"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 8192,
  "neighbors": [
    {
      "edge_id": "merge-state-to-intent-proof",
      "to_card_id": "sqw.recovery.conflict-intent-and-proof",
      "edge_mode": "hard",
      "hard_predicate_id": "merge-sides-identified",
      "missing_decision": "Conflict intent and proof remain unresolved after identifying sides",
      "required_evidence": "Base, ours, theirs, operation, and affected tests",
      "evict_when": "Conflict resolution intent and proof contract are recorded"
    }
  ]
}
---
# Merge State and Sides

## Decision this card owns
Identify the active Git operation and the exact meaning of base, ours, and theirs before resolving content.

## Use when
- Merge, rebase, cherry-pick, or revert conflict state is active.

## Do not use when
- No conflict operation exists or the repository itself is damaged.

## Required inputs
- Operation markers, current HEAD, source/upstream or selected commit, sequencer position, status, conflict stages, pre-existing index/worktree state, allowed path subset, and repository-action authority.

## Procedure
1. Freeze an operation manifest before edits: operation type, current HEAD, source/upstream or selected commit, sequencer step, conflict paths/stages, pre-existing staged/dirty paths, protected paths, and authorized resolution allowlist.
2. Record exact side semantics. For merge, ours is current HEAD and theirs is the merged tip; for rebase, ours is the new base/rebased history and theirs is the commit being replayed; for cherry-pick, ours is current HEAD and theirs is the selected commit; for revert, ours is current HEAD and theirs is the reverse change constructed toward the selected commit's parent.
3. Bind base/ours/theirs to immutable revisions or stage-blob identities. Never infer intent from the labels alone.
4. Separate conflict paths from pre-existing index/worktree changes, untracked/ignored material, and generated state; protect everything outside the admitted subset.
5. If the operation, sequencer step, HEAD, conflict set, or unrelated dirty set changes, invalidate the manifest and freeze a new one before further work.
6. Request semantic intent/proof only after side identities and the admitted subset are stable; do not edit, stage, continue, commit, abort, or skip here.

## Output contract
- `operation_manifest`, `operation`, `sequencer_position`, `base_revision`, `ours_revision`, `theirs_revision`, `conflict_paths`, `preexisting_index`, `protected_paths`, `allowed_resolution_subset`, `invalidation_triggers`, and `next_edge_id`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `merge-state-to-intent-proof` | Conflict intent and proof remain unresolved after identifying sides | Base, ours, theirs, operation, and affected tests | `sqw.recovery.conflict-intent-and-proof` | Conflict resolution intent and proof contract are recorded |

## Stop
Stop at the frozen side-identity/operation-manifest boundary before any content edit or repository state transition.
