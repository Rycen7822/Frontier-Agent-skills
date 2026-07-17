---
{
  "card_id": "sqw.entry.recovery",
  "card_version": 2,
  "kind": "decision",
  "decision_id": "sqw.select.entry.recovery",
  "required_artifact_ids": [],
  "produced_artifact_ids": [
    "workflow-intake"
  ],
  "max_bytes": 4096
}
---
# Recovery Entry

## Decision this card owns
Classify observed repository recovery state without performing destructive cleanup by default.

## Use when
- A merge, index/ref/worktree fault, interrupted operation, or explicitly authorized cleanup blocks normal work.

## Do not use when
- The repository is healthy and only product behavior is failing.

## Required inputs
- Read-only repository/operation observations, source identity, protected dirty/untracked/generated paths, and exact recovery or cleanup authority.

## Procedure
1. Observe status, operation markers, refs, index, worktrees, locks, and task-owned residue without changing them.
2. Inventory and preserve every path or process not certainly owned by this recovery.
3. Distinguish active merge intent, repository damage/incomplete operation, and optional cleanup.
4. Select exactly one recovery class from evidence; do not combine conflict repair, repository repair, and cleanup opportunistically.
5. Bind allowed effects, backup/rollback, stop conditions, and post-action proof; destructive actions require exact authorization.
6. Emit `workflow-intake` plus one typed recovery decision request, or block when state/authority is insufficient.

## Output contract
- One `workflow-intake` with recovery class, observed state, protected inventory, authority/effects, required evidence, rollback, blocker, and typed recovery decision request.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop after classifying one recovery path or proving that safe recovery cannot yet proceed.
