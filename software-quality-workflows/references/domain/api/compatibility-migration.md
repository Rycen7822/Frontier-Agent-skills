---
{
  "card_id": "sqw.domain.api.compatibility-migration",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "contract_decision",
    "consumer_inventory",
    "rollout_constraints"
  ],
  "produces": [
    "migration_contract",
    "removal_gate"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# API Compatibility Migration

## Decision this card owns
Define staged coexistence, cutover, rollback, and removal proof for a multi-consumer public contract change.

## Use when
- Consumers cannot move atomically or versions must coexist.

## Do not use when
- The change is internal or every consumer changes in one bounded atomic release.

## Required inputs
- Consumer/version inventory, old and new contracts, rollout authority, telemetry, and rollback limits.

## Procedure
1. **Expand:** define the compatible expansion surface.
2. **Migrate:** order producer and consumer migrations.
3. Define divergence detection during coexistence.
4. Set rollback and last-compatible-state boundaries.
5. **Contract:** remove the old path only after evidence shows no old readers, writers, callers, stored forms, fixtures, generated artifacts, or supported clients remain.
6. Record cutover/release authority separately from technical readiness and never treat this card as publication approval.

## Output contract
- `expand_step`, `consumer_steps`, `coexistence_policy`, `rollback_boundary`, `removal_gate`, and `cutover_authority_ref`.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop after the migration contract is executable and no dual source of truth is left undefined.
