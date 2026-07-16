---
{
  "card_id": "wp.migration.deprecation-and-rollout",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "deprecated_surface",
    "consumer_evidence",
    "replacement_contract"
  ],
  "produces": [
    "migration_rollout_removal_plan"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Deprecation, Migration, and Rollout

## Decision this card owns
Plan replacement, consumer migration, rollout/rollback, and evidence-gated removal of one deprecated surface.

## Use when
- An API/schema/CLI/plugin/runtime/data/config/flag/generated surface or subsystem with possible consumers will be replaced or removed.

## Do not use when
- No consumer contract changes or the task is only authorized local cleanup.

## Required inputs
- Old/new surface identities and owners; code/external/generated/config/doc/test consumers; compatibility/usage evidence; rollout authority; consumer oracle; rollback/removal constraints.

## Procedure
1. Inventory all consumer classes and classify each active, migrated, unknown, or intentionally supported using fresh search/runtime/release evidence.
2. Define the replacement owner seam and proof before choosing direct rewrite, strangler, adapter, dual-run/shadow, flag, or staged rollout.
3. Give temporary compatibility paths an owner, tests, cohorts, expiry, rollback window, and deletion gate; prevent new usage where safe.
4. Migrate bounded consumer slices and prove behavior/compatibility after each; unknown external consumers remain blocking, never counted as zero.
5. Require fresh zero-active-usage/consumer-oracle evidence before removal. Under closure, bind each removal constraint as hard contract evidence a candidate cannot waive.
6. Delete old implementation plus obsolete-only tests/docs/examples/config/flags/snapshots/notices, then audit old names/tokens/paths and classify intentional residue.
7. Record rollout monitoring, halt/revert conditions, authority gates, and post-deletion restoration path.

## Output contract
- Baseline/consumer matrix, replacement/migration shape, ordered slices/cohorts, compatibility and usage proof, rollback/removal gates, deletion inventory, residue audit, and blockers.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop only when replacement precedes migration and deletion is gated by fresh consumer evidence.
