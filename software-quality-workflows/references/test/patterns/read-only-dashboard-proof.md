---
{
  "card_id": "sqw.test.patterns.read-only-dashboard-proof",
  "card_version": 1,
  "kind": "recipe",
  "consumes": [
    "read_only_dashboard_contract",
    "backing_store_identity",
    "public_launch_surface"
  ],
  "produces": [
    "read_only_dashboard_proof"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Read-Only Dashboard Proof Pattern

## Decision this card owns
Prove a local inspection dashboard reads the intended store, exposes correct API/browser behavior, and leaves persistent state unchanged.

## Use when
- A local dashboard/inspection UI reads records, streams updates, or has a source-tree versus installed browser surface.

## Do not use when
- UI writes the store, is internet-facing, or needs product-specific deployment/security design.

## Required inputs
- Read-only store contract and identity, API schema, launch/installed entrypoints, stream semantics, isolated fixture/copy, loopback process/port, and browser evidence needs.

## Procedure
1. Use an isolated copy or explicitly read-only connection; missing data must report absence without creating a store.
2. Test data layer, API, launch entrypoint, and browser surface separately; exercise both source and installed paths when different.
3. For streams, prove initial data, incremental events, disconnect/end behavior, and client cleanup.
4. Observe actual process identity, selected data root, loopback address, assigned port, rendered/asynchronous state, console, and network responses.
5. Confirm the backing store is unchanged, then stop only task-owned process/browser/port and remove only the isolated copy.

## Output contract
- Store before/after identity, layer-by-layer evidence, source/installed path coverage, stream/browser observations, process/port identity, failures, and cleanup proof.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at dashboard proof; never clean or probe a shared data root without authority.
