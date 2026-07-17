---
{
  "card_id": "sqw.recovery.conflict-recovery",
  "card_version": 2,
  "kind": "procedure",
  "decision_id": "sqw.select.recovery.conflict-recovery",
  "required_artifact_ids": [
    "workflow-intake"
  ],
  "produced_artifact_ids": [
    "recovery-conflict-recovery"
  ],
  "max_bytes": 8192
}
---
# Conflict Recovery

## Decision this card owns
Freeze an active Git conflict operation, reconstruct intended behavior across its exact sides, and prove a bounded resolution without inferring repository-transition authority.

## Use when
- `workflow-intake` identifies an active merge, rebase, cherry-pick, or revert conflict whose content is authorized for semantic resolution.

## Do not use when
- Repository mechanics are damaged, no conflict operation exists, the allowed subset is unknown, or both behaviors require unresolved product intent.

## Required inputs
- `workflow-intake`; operation markers and sequencer position; current HEAD and source/selected commit; conflict stages; pre-existing index/worktree/untracked state; protected and allowed paths; base/ours/theirs blobs and commits; requirements, callers, tests, runtime contracts and generated-source provenance; proof authority; and separately stated repository-action authorities.

## Procedure
1. Before edits, freeze an operation manifest with operation type, HEAD, source or selected commit, sequencer step, conflict paths/stages, pre-existing staged/dirty/untracked state, protected paths, and exact resolution allowlist.
2. Bind immutable side identities correctly: merge uses current HEAD as ours and merged tip as theirs; rebase uses the new base/history as ours and replayed commit as theirs; cherry-pick uses current HEAD and selected commit; revert uses current HEAD and the reverse change toward the selected commit's parent. Labels alone never prove intent.
3. Separate admitted conflicts from unrelated state and invalidate the manifest if operation, sequencer step, HEAD, conflict set, or unrelated dirty set changes.
4. Compare base→ours and base→theirs with commits, requirements, authoritative generated sources, callers, tests, and runtime contracts. Classify each path/hunk as independent, composable, incompatible, rename/delete, add/add, generated, or lockfile/resolution conflict.
5. Reconstruct the smallest combined contract. Regenerate derived files or lockfiles only with declared tool/provenance and authority; pause when behaviors cannot coexist or intent remains ambiguous.
6. Stage only explicitly admitted resolved paths, preserve every pre-existing index entry, inspect the actual staged set against the manifest, and run focused plus affected contract/integration proof.
7. Record preserved intent, rejected content, limitations, and next required repository action. Stage, continue, skip, abort, commit, and push remain independent authority gates.

## Output contract
- One `recovery-conflict-recovery` with operation/side identities, frozen manifest and invalidation triggers, conflict classification, per-path resolution, preserved/rejected intent, staged-path proof, test evidence, residual limits, and separately required repository-action authority.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop after the admitted resolution is staged and proved, or earlier on stale state or ambiguous intent; do not continue, skip, abort, commit, or push without separate authority.
