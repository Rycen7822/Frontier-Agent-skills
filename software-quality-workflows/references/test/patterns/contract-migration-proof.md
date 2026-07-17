---
{
  "card_id": "sqw.test.patterns.contract-migration-proof",
  "card_version": 2,
  "kind": "recipe",
  "decision_id": "sqw.select.test.patterns.contract-migration-proof",
  "required_artifact_ids": [
    "workflow-intake"
  ],
  "produced_artifact_ids": [
    "test-patterns-contract-migration-proof"
  ],
  "max_bytes": 8192
}
---
# Contract Migration Proof Pattern

## Decision this card owns
Prove a legacy/current comparison or approved semantic replacement preserves required identity, rejects real differences, and reaches every consumer and public/installed surface.

## Use when
- `workflow-intake` identifies a retired name, payload, schema, alias, state identity or behavior, or optional schema differences cause false refresh/rewrite despite approved semantic equivalence.

## Do not use when
- The difference is an intentional semantic/provenance/addition/removal/value change or a local rename with no compatibility effect.

## Required inputs
- `workflow-intake`; approved new contract and old compatibility/rejection decision; versioned legacy/current fixtures; comparison owner's required identity and optional metadata rules; consumer and source/test/schema/doc/example/generated/dormant adapter inventory; real diff/scheduling path and threshold; migration/rollback plan; installed/public surfaces; and affected gates and authorities.

## Procedure
1. Characterize equivalent legacy/current fixtures and explicit semantic-delta controls. Add targeted REDs for the new contract, old compatibility or rejection, and the real false-diff/scheduling path; reach targeted GREEN before broad cleanup.
2. At the comparison owner seam, separate required identity from optional/current metadata without rewriting stored source. Preserve true additions, removals, values, provenance and current-schema thresholds.
3. Run broader proof and classify every failure as stale old-contract test, residual old behavior, genuine regression, harness gap, unavailable environment, or permission denial.
4. Search code, tests, fixtures, schemas, docs, examples, generated assets and dormant entrypoints for retired symbols; treat matches as candidates and inspect structured contracts, call paths and consumers before deletion or residue claims.
5. Prove equivalent legacy input no longer schedules unnecessary work while intentional semantic change still does. Exercise public and installed paths that can retain stale packaged/generated content and assert the approved compatibility or rejection behavior.
6. Test any source migration separately and only with authority. Remove helpers only after consumer/rollback accounting; retain migration and rollback artifacts until consumers and affected gates pass.

## Output contract
- One `test-patterns-contract-migration-proof` with fixture/schema and new/old identities, false-diff and compatibility/rejection RED/GREEN, required/optional field decision, real scheduling/threshold controls, consumer/surface coverage, classified broad-gate results, inspected residuals, public/installed/generated proof, migration authority, rollback, cleanup, and blockers.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at semantic migration proof; a clean text scan is not semantic proof or migration authority, and real contract/provenance differences cannot be normalized away.
