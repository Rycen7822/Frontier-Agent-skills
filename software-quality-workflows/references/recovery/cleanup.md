---
{
  "card_id": "sqw.recovery.cleanup",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "cleanup_authority",
    "object_inventory",
    "retention_requirements"
  ],
  "produces": [
    "cleanup_result",
    "retention_proof"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Authorized Cleanup

## Decision this card owns
Remove only an explicitly authorized bounded set of task-owned artifacts or redundant source while proving retained state and behavior remain.

## Use when
- Cleanup authority and an exact object or source-change set are both established, including a preserved behavior/retention contract.

## Do not use when
- Ownership or behavior is uncertain, evidence may still be valuable, repository/workspace recovery is needed, or cleanup is merely convenient.

## Required inputs
- Exact object/change inventory, ownership and reachability evidence, preserved behavior contract, retention/archive requirements, focused proof, and cleanup authority.

## Procedure
1. Classify the bounded request as artifact cleanup, source simplification, or both; reject workspace reorganization and recovery work from this card.
2. For artifacts, classify every item as retained, archived, removable, or uncertain. Exclude unrelated, user-owned, needed generated, and evidentiary state.
3. For source, use reuse, quality, and efficiency lenses to identify proven dead/redundant branches, wrappers, compatibility paths, or duplication; confirm reachability, public contracts, callers, tests, and runtime/config consumers before removal.
4. Freeze the exact allowlist, preserved behavior/retention contract, rollback/archive plan, and dry-run inventory when removal is material.
5. Archive required evidence, then remove only allowlisted items or source spans. Do not fold opportunistic refactors into the cleanup diff.
6. Inspect the semantic diff and verify focused behavior, affected contracts, required retention, absence, and unrelated-path preservation.
7. Report uncertain candidates and residual duplication instead of escalating the cleanup scope.

## Output contract
- `cleanup_mode`, `removed_objects_or_spans`, `retained_objects`, `preserved_behavior`, `archive_refs`, `semantic_diff`, `post_cleanup_proof`, and `unresolved_candidates`.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop without removal whenever authority, ownership, reachability, retention, or preserved behavior is uncertain.
