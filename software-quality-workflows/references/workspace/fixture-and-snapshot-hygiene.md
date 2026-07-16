---
{
  "card_id": "sqw.workspace.fixture-and-snapshot-hygiene",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "fixture_snapshot_contract",
    "source_and_provenance_inventory",
    "candidate_boundary"
  ],
  "produces": [
    "fixture_snapshot_hygiene_artifact"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Fixture and Snapshot Hygiene

## Decision this card owns
Create, move, retain, and validate bounded active fixtures/snapshots without copying unrelated state, escaping boundaries, or confusing historical output with active proof.

## Use when
- A copied fixture, snapshot, runner input, generated candidate, or historical evidence set is added/relocated/curated.

## Do not use when
- The test's lifecycle/oracle is unresolved, the material is a prototype, or general workspace ownership is unknown.

## Required inputs
- Fixture/snapshot purpose and owner, source/provenance revision, minimal material set, boundary/link policy, active consumers/discovery, generated/cache/credential exclusions, candidate acceptance contract, history/retention, and edit authority.

## Procedure
1. Copy only material required by the oracle; exclude caches/build output/credentials/repository metadata/unrelated history during collection.
2. Reject links/resolution escaping the boundary unless explicitly required and isolated; keep provenance stable without reader-facing private machine paths.
3. Separate active fixtures/runners from historical run artifacts so test discovery/search cannot consume both; preserve immutable old paths while updating only active pointers.
4. Verify schema/identity/count/dedup and consumer resolution after moves; recheck ignore rules at the new nested path and actual candidate/staged set.
5. Keep generated/rejected candidates outside canonical fixtures until accepted by the exact pattern/lifecycle owner; run bounded secret/private-data inspection on the real candidate set.
6. Prove fixture runner/snapshot behavior and path boundary, then remove only superseded task-owned copies after replacement/retention evidence.

## Output contract
- Fixture/snapshot identity/purpose/provenance, included/excluded inventory, boundary/link and private-path proof, active/history separation, consumer/ignore/staged status, acceptance/replacement evidence, cleanup and blockers.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at a bounded traceable fixture/snapshot; never normalize sensitive/generated state into source or delete unaccepted evidence.
