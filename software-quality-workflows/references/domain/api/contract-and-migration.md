---
{
  "card_id": "sqw.domain.api.contract-and-migration",
  "card_version": 2,
  "kind": "procedure",
  "decision_id": "sqw.select.domain.api.contract-and-migration",
  "required_artifact_ids": [
    "workflow-intake"
  ],
  "produced_artifact_ids": [
    "domain-api-contract-and-migration"
  ],
  "max_bytes": 8192
}
---
# API Contract and Migration

## Decision this card owns
Define a public contract change, its real-boundary proof, and any staged compatibility migration/removal gate.

## Use when
- An externally consumed API, schema, protocol, CLI, public type, generated client, or serialized form changes.

## Do not use when
- The change is entirely private and no consumer can observe it.

## Required inputs
- `workflow-intake`; current/requested contract; producers/consumers/versions; names/types/fields/defaults/errors/order/IDs/timing/effects; valid/invalid fixtures; rollout/cutover authority; telemetry; and rollback constraints.

## Procedure
1. Inventory every producer/consumer, supported version, example, generated client, fixture/doc, stored form, and observable field/default/error/order/side effect.
2. Record authorization assumptions, idempotency/retry/partial success, pagination/collection/string/recursion/file bounds, version behavior, and machine-readable failure classes.
3. Classify additive, compatible transition, behavior-changing, or breaking; treat new enum/control values as unsafe when exhaustive consumers can fail.
4. Define preserved/changed behavior and allowed variation. Select representative valid/invalid inputs, validate shape and semantics before business logic/use/rendering, keep authorization outside forgeable payload fields, and publish the unknown-field rule.
5. Prove positive, negative, compatibility, defaults, versions, ordering, serialization, idempotency, error, and resource behavior through the real API/protocol/CLI/generated/installed surface with independent fixed expectations and synthetic non-sensitive data.
6. If consumers cannot move atomically, define expand, ordered producer/consumer migration, coexistence precedence, divergence detection, rollback/last-compatible state, and contract phase.
7. Remove the old path only after fresh evidence finds no old readers, writers, callers, stored forms, fixtures, generated artifacts, or supported clients. Keep technical readiness separate from cutover/release/publication authority.

## Output contract
- One `domain-api-contract-and-migration` with contract surface, compatibility class, consumer/version inventory, preserved/changed behavior, positive/negative/compatibility/public gates, expand/migrate/coexistence/rollback/removal contract, cutover authority ref, evidence, gaps, and blocker.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop when the public boundary and migration/removal proof are executable; do not grant publication authority.
