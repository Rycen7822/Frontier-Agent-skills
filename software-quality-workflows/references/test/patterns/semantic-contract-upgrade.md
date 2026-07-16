---
{
  "card_id": "sqw.test.patterns.semantic-contract-upgrade",
  "card_version": 1,
  "kind": "recipe",
  "consumes": [
    "approved_new_semantic_contract",
    "consumer_compatibility_inventory",
    "migration_plan"
  ],
  "produces": [
    "semantic_contract_upgrade_proof"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Semantic Contract Upgrade Pattern

## Decision this card owns
Prove a retired name, payload, schema, alias, state identity, or behavior is replaced consistently across all approved surfaces.

## Use when
- One semantic/compatibility contract changes across multiple source, test, generated, documented, public, or installed surfaces.

## Do not use when
- The change is a local rename with no semantic or compatibility effect.

## Required inputs
- Approved new contract and compatibility/rejection decision, consumer/surface inventory, generated artifacts, migration/rollback plan, and affected gates.

## Procedure
1. Add targeted REDs for the new contract and explicit old-contract compatibility or rejection, then reach targeted GREEN before broad cleanup.
2. Run broader proof and classify failures as stale old-contract test, residual old behavior, genuine regression, harness gap, unavailable environment, or permission denial.
3. Search code, tests, fixtures, schemas, docs, examples, generated assets, and dormant entrypoints for retired symbols.
4. Treat text matches as candidates; inspect structured contracts and call paths before deleting or declaring residue.
5. Exercise public and installed surfaces that can retain stale packaged/generated content.
6. Remove helpers only after consumer and rollback accounting; keep approved migration/rollback until consumers are verified.

## Output contract
- New/old behavior evidence, consumer/surface coverage, classified broad-gate outcomes, inspected residuals, public/installed proof, compatibility/rollback status, cleanup, and blockers.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at semantic-upgrade evidence; a clean text scan is neither semantic proof nor migration authority.
