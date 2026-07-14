# Repository Recovery

Use this reference when repository files or a subtree were accidentally deleted or overwritten and the user wants recovery. Do not use it for ordinary cleanup, workspace reorganization, or intentional rollback of a known change.

Recovery changes repository state. Resolve scope and authorization through the [authority and scope owner](authority-and-scope.md), and prove the restored result through [verification discipline](verification-discipline.md).

## Recovery sequence

1. Stop this task from initiating further writes to the affected scope, then inspect repository status, the exact affected paths, and current working-tree changes without modifying them. Coordinate a pause only with known writers and their owner; do not signal, stop, or reconfigure an unknown process, service, user task, or concurrent agent.
2. Classify every missing item as tracked, untracked, ignored, generated, external, or unknown. Do not assume version control contains all lost work.
3. Preserve current evidence: deletion status, surviving adjacent files, timestamps, references from configs or logs, and any unrelated local modifications that must not be overwritten.
4. Search non-mutating recovery sources in order: current version-control objects, stashes or branches, operating-system recovery facilities, editor/local history, backups, artifact stores, and durable application data.
5. Build an explicit restore map from each affected path to its selected source. Mark whether recovery is exact, reconstructed, or unavailable.
6. After authorization, restore tracked content with the narrowest path scope. Avoid repository-wide restore operations when only a subtree is affected.
7. Recover untracked content only from verified copies. If reconstruction is necessary, derive it from durable sources and label it reconstructed.
8. Reconcile preserved local modifications deliberately; do not reapply remembered edits without an evidence source.
9. Verify repository status, affected file inventory, relevant contracts, and the user-facing behavior proportional to the recovered scope.

## Tracked versus untracked

| Class | Recovery expectation |
|---|---|
| Tracked, committed | Usually recoverable exactly from the selected revision. |
| Tracked, uncommitted | Recoverable only from another working copy, patch, stash, editor history, backup, or retained object. |
| Untracked/ignored | Not recoverable from ordinary repository history; locate a copy or reconstruct. |
| Generated | Prefer deterministic regeneration from authoritative inputs after restoring those inputs. |
| External state | Recover through the owning store's supported export/backup path, not by guessing files. |

## Safety rules

- Do not use broad destructive history or workspace cleanup operations during recovery.
- Do not overwrite unrelated dirty work to make the tree appear clean.
- Do not remove surviving evidence, temporary copies, or unknown files until recovery is verified.
- Do not treat a restored tracked tree as proof that untracked outputs were recovered.
- Do not restart or reconfigure a service merely because its source tree changed; handle runtime refresh only when separately in scope and authorized.

## Closeout checklist

- Every requested path is classified as exact, reconstructed, unavailable, or intentionally excluded.
- The restore source and target are traceable.
- Unrelated local changes remain intact.
- Generated outputs were regenerated only from restored authoritative inputs.
- Focused checks cover the restored contracts; broader checks match the blast radius.
- Remaining gaps are explicit, especially for untracked, ignored, or externally stored content.
