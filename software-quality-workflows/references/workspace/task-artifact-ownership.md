---
{
  "card_id": "sqw.workspace.task-artifact-ownership",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "workspace_artifact_inventory",
    "ownership_and_consumer_evidence",
    "move_delete_authority"
  ],
  "produces": [
    "task_artifact_ownership_and_relocation_contract"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Task-Artifact Ownership

## Decision this card owns
Classify task artifacts, choose safe location/retention/relocation/removal, and preserve durable conclusions and consumers before authorized deletion.

## Use when
- Scratch, worknotes, generated outputs, archives, evidence, snapshots, copied artifacts, or staged candidates need ownership/organization/retention decisions.

## Do not use when
- The object is active source/config, lost content needs recovery, or source-code simplification is the requested outcome.

## Required inputs
- Bounded inventory with path/type/size/repository status/producer/owner/consumers/lifecycle, project location rules, active references/ignore behavior, historical provenance, concurrency, retention needs, and move/delete/stage authority.

## Procedure
1. Classify active source/config; task scratch; active fixture/runner; generated/derived; evidence/provenance; or unknown/third-party. Leave unknown/external/concurrently changed material in place.
2. Keep new scratch under one task-specific temporary root selected by project instructions; generated state is not sole truth and historical evidence is immutable or relocation-traceable.
3. Before moving, inspect active config/tests/scripts/docs/ignore/path consumers and define old→new, owner, updates, rollback. Move only authorized entries and preserve historical embedded paths unless normalization is requested.
4. Verify destinations, consumers, status, ignore behavior, and cheapest runner/syntax check; inspect actual staged paths and reject unintended scratch/cache/export/secret/private/generated candidates without broadening the stage set.
5. Before deletion, extract durable conclusion/provenance/accepted delta/reusable verifier to its canonical owner, re-read that destination and prove consumers resolve there.
6. Remove only exact task-owned items whose retention conditions are met, verify absence plus unrelated retention, and report protected/external blockers rather than escalating cleanup.

## Output contract
- Classified inventory, task root, ownership/lifecycle/retention, relocation map and consumer updates, staged-candidate disposition, compacted durable refs, authorized removals/post-proof, unknowns/blockers.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop when every in-scope artifact has a known disposition; never use broad cleanup to solve uncertain ownership.
