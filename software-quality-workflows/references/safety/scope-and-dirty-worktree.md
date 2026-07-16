---
{
  "card_id": "sqw.safety.scope-and-dirty-worktree",
  "card_version": 1,
  "kind": "safety",
  "consumes": [
    "request_mode_decision",
    "authority_decision",
    "source_identity",
    "workspace_observation"
  ],
  "produces": [
    "scope_decision",
    "scope_manifest_requirements"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Scope and Dirty Worktree

## Decision this card owns
Set the smallest defensible source and path boundary while preserving user-owned, generated, ignored, and concurrent work.

## Use when
- The worktree is dirty or concurrent, scope must survive a handoff, coverage spans multiple paths, or revision identity is uncertain.

## Do not use when
- A fresh M0 in-session scope decision already identifies one owner seam and unrelated work is not implicated.

## Required inputs
- Request and authority decisions, logical repository root, current revision or explicit unversioned identity, status/diff evidence, requested exclusions, and proposed read/write paths.

## Procedure
1. For M0, keep only an in-session scope record: request mode, one owner/path seam, protected unrelated work, source identity, side-effect ceiling, and proof boundary. Do not create durable state by default.
2. Require a canonical durable manifest for M2/M3, delegation, broad review, dirty/concurrent work, uncertain revision, or cross-context continuation.
3. Classify tracked, untracked, ignored, generated, vendor, binary, renamed, and deleted paths explicitly; none is automatically disposable or out of scope.
4. Use one scope identity for reads, scans, edits, tests, review slices, fixes, and final reporting. Do not silently switch between staged, commit, worktree, or hosted-change views.
5. Derive every edit, move, staging action, and cleanup target from the writable allowlist. Preserve unrelated and concurrent changes.
6. Clean only task-created artifacts with certain ownership, then re-observe remaining state.

## Output contract
- `scope_decision`: logical root, source identity, readable/writable/protected boundaries, exclusions, and ambiguity.
- `scope_manifest_requirements`: whether durable state is required and the path/snapshot fields the controller must canonicalize and hash outside model context.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop before an edit that could overwrite unrelated work, before cleanup with uncertain ownership, or when source/scope identity cannot be established safely.
