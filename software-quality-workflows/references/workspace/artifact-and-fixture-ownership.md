---
{
  "card_id": "sqw.workspace.artifact-and-fixture-ownership",
  "card_version": 2,
  "kind": "procedure",
  "decision_id": "sqw.select.workspace.artifact-and-fixture-ownership",
  "required_artifact_ids": [
    "workflow-intake"
  ],
  "produced_artifact_ids": [
    "workspace-artifact-and-fixture-ownership"
  ],
  "max_bytes": 8192
}
---
# Artifact and Fixture Ownership

## Decision this card owns
Classify, locate, move, retain, stage, accept, or remove bounded task artifacts and fixtures while preserving provenance, consumers, history, boundaries, and durable conclusions.

## Use when
- `workflow-intake` identifies scratch, worknotes, generated output, evidence, archives, copied material, active fixtures/runners, snapshots, or staged candidates needing an ownership or lifecycle decision.

## Do not use when
- The object is active product source/config, lost content needs recovery, source simplification is the requested outcome, the test oracle/lifecycle is unresolved, or the material is a prototype.

## Required inputs
- `workflow-intake`; bounded inventory with path/type/size/status/producer/owner/consumers/lifecycle; fixture or snapshot purpose and oracle owner; source/provenance revision; project location and link rules; active discovery/consumers/ignore behavior; generated/cache/credential/private-data exclusions; acceptance and replacement contract; retention/history/concurrency; and exact move/delete/stage authority.

## Procedure
1. Classify every object as active source/config, task scratch, active fixture/runner, generated/derived, evidence/provenance, or unknown/third-party. Leave unknown, external, and concurrently changed material in place.
2. Keep new scratch under one project-approved task root. Copy only the minimal oracle material; exclude cache/build output, credentials, repository metadata, unrelated history, secrets and private data. Generated state is not sole truth.
3. Preserve stable provenance without reader-facing private machine paths. Reject links escaping the fixture boundary unless explicitly required and isolated; separate active fixtures/runners from immutable or relocation-traceable historical run artifacts.
4. Before moving, inspect every config/test/script/doc/ignore/path consumer and define old→new mapping, owner, updates, rollback, and retained embedded historical paths. Move only authorized entries.
5. Verify destination schema, identity, count/dedup, consumer resolution, boundary/link policy, ignore behavior, actual candidate/staged set, and cheapest runner or syntax check. Rejected/generated candidates stay outside canonical fixtures until the exact lifecycle owner accepts them.
6. Before deletion, extract the durable conclusion, provenance, accepted delta, and reusable verifier to the canonical owner; reread it and prove all consumers resolve there. Remove only superseded task-owned copies with replacement/retention evidence.
7. Report classified inventory, active/history boundary, unknowns and blocked items explicitly; never broaden the action into workspace reorganization or cleanup of uncertain evidence.

## Output contract
- One `workspace-artifact-and-fixture-ownership` with classified inventory, task root, ownership/lifecycle/retention, provenance and inclusion/exclusion set, boundary/link/private-data proof, active/history separation, relocation and consumer updates, staged/fixture acceptance, durable refs, authorized removals, post-action proof, unknowns, and blockers.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop when every in-scope object has a known evidence-backed disposition; do not normalize sensitive/generated state into source or delete unaccepted evidence.
