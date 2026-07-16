---
{
  "card_id": "sqw.domain.api.contract-change",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "public_contract_inventory",
    "consumer_evidence",
    "requested_change"
  ],
  "produces": [
    "contract_decision",
    "compatibility_need"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 4096,
  "neighbors": [
    {
      "edge_id": "api-to-compatibility-migration",
      "to_card_id": "sqw.domain.api.compatibility-migration",
      "edge_mode": "semantic",
      "missing_decision": "Multiple consumers or staged cutover require a migration contract",
      "required_evidence": "Consumer versions and rollout constraints",
      "evict_when": "Compatibility and migration policy are recorded"
    },
    {
      "edge_id": "api-to-boundary-validation",
      "to_card_id": "sqw.domain.api.boundary-validation",
      "edge_mode": "semantic",
      "missing_decision": "Public boundary negative and compatibility oracles are unresolved",
      "required_evidence": "Boundary schema and consumer-visible error behavior",
      "evict_when": "Boundary validation contract is recorded"
    }
  ]
}
---
# Public Contract Change

## Decision this card owns
Define the intended public API, schema, protocol, CLI, or public-type change and its compatibility class.

## Use when
- Route facts prove that an externally consumed contract is implicated.

## Do not use when
- The change is entirely internal and consumers cannot observe the surface.

## Required inputs
- Current contract, consumers, version support, errors/defaults, and the requested observable change.

## Procedure
1. Inventory consumers/producers, examples, generated clients, fixtures/docs, and observable names/types/fields/defaults/errors/ordering/IDs/timing/side effects.
2. Record authorization assumptions, idempotency/retry/partial success, pagination/bounds, version behavior, and every known consumer/version boundary.
3. Classify as additive, compatible-transition, behavior-changing, or breaking; additions such as enum values are not safe when exhaustive consumers can fail.
4. State preserved/changed behavior, allowed variation, and one machine-readable error/failure contract that does not require parsing prose.
5. Decide whether staged migration or a new boundary oracle is missing.
6. Emit the public contract decision and at most one next edge.

## Output contract
- `contract_surface`, `compatibility_class`, `preserved_behavior`, `changed_behavior`, `consumer_set`, and `next_edge_id|null`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `api-to-compatibility-migration` | Multiple consumers or staged cutover require a migration contract | Consumer versions and rollout constraints | `sqw.domain.api.compatibility-migration` | Compatibility and migration policy are recorded |
| `api-to-boundary-validation` | Public boundary negative and compatibility oracles are unresolved | Boundary schema and consumer-visible error behavior | `sqw.domain.api.boundary-validation` | Boundary validation contract is recorded |

## Stop
Stop when compatibility is decided or one missing migration/validation decision is selected.
