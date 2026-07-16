---
{
  "card_id": "sqw.recovery.conflict-intent-and-proof",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "merge_state_record",
    "side_content",
    "behavior_contracts"
  ],
  "produces": [
    "resolution_contract",
    "recovery_proof"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Conflict Intent and Proof

## Decision this card owns
Reconstruct intended behavior across conflicting sides and define proof for the bounded resolution.

## Use when
- Operation and side identities are known and conflict content requires semantic resolution.

## Do not use when
- Repository state remains ambiguous or an abort/continue action lacks authority.

## Required inputs
- Frozen operation manifest; base/ours/theirs blobs and commits; commit messages/diffs; requirements and authoritative generated sources; callers, tests, runtime contracts; protected worktree/index state; and staging/proof authority.

## Procedure
1. Compare base→ours and base→theirs with their commits, requirements, callers, tests, and runtime contracts; labels alone are not intent evidence.
2. Classify each path/hunk as independent, composable, semantically incompatible, rename/delete, add/add, generated, or lockfile/resolution conflict.
3. Reconstruct the combined contract from authoritative sources first. Regenerate derived files and lockfiles with their declared tool/provenance when authorized instead of hand-merging generated text.
4. Define the smallest conflict-only edit and rejection rationale. Pause when both behaviors cannot coexist or product intent remains ambiguous.
5. Stage only explicitly admitted resolved paths, then inspect the actual staged set against the frozen manifest and preserve every pre-existing index entry.
6. Run focused proof plus affected integration/contract checks, inspect the staged semantic diff, and record preserved intent, rejected content, and residual limitations.
7. Treat stage, continue, skip, abort, commit, and push as separate authority gates; never infer one from permission to resolve content.

## Output contract
- `conflict_classification`, `resolution_by_path`, `preserved_intent`, `rejected_content`, `staged_path_proof`, `proof_results`, `residual_limitations`, and `next_repository_action_authority`.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop after the admitted resolution is staged and proved, or earlier on ambiguous intent; do not auto-continue, skip, abort, commit, or push.
