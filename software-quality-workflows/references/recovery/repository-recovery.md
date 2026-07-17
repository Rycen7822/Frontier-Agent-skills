---
{
  "card_id": "sqw.recovery.repository-recovery",
  "card_version": 2,
  "kind": "procedure",
  "decision_id": "sqw.select.recovery.repository-recovery",
  "required_artifact_ids": [
    "workflow-intake"
  ],
  "produced_artifact_ids": [
    "recovery-repository-recovery"
  ],
  "max_bytes": 8192
}
---
# Repository Recovery

## Decision this card owns
Restore a bounded repository/index/ref/operation invariant while preserving unrelated state.

## Use when
- Repository mechanics, not product behavior, are damaged or interrupted.

## Do not use when
- A normal merge conflict or optional cleanup is the only issue.

## Required inputs
- `workflow-intake`; status; refs and reflogs; object/index/worktree evidence; active operation; repository configuration/remotes; artifact provenance; protected paths; and exact allowed recovery actions.

## Procedure
1. Snapshot refs, operation markers, index, worktree, status, configuration, and user-owned state without changing them.
2. Classify affected material as tracked committed, tracked uncommitted, untracked, ignored, generated/derived, or external; never treat one class as a recovery source for another without provenance.
3. Identify the violated invariant and inspect non-mutating sources in order: current refs/index/worktree, operation metadata and reflogs, reachable/dangling objects or stashes, declared remotes/backups, then reproducible generation inputs.
4. Build a per-object restore map classified as exact, reconstructed, or unavailable, with source identity and confidence. Preserve copies of irreplaceable evidence and unrelated local modifications before repair.
5. Choose the least destructive reversible action that restores only the named invariant, and apply it only within explicit recovery authority.
6. Re-observe refs, index, worktree, operation state, protected paths, and restored content; compare against the restore map and run the cheapest relevant integrity/behavior check.
7. Report unavailable content and blocked actions plainly; do not invent missing bytes or broaden into cleanup.

## Output contract
- One `recovery-repository-recovery` with artifact classification, violated invariant, restore map and source identities, repair actions, preserved paths, post-recovery state, integrity proof, and blocker.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop when repository invariants are restored or the next safe action exceeds authority.
