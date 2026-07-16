---
{
  "card_id": "sqw.test.patterns.legacy-manifest-comparison",
  "card_version": 1,
  "kind": "recipe",
  "consumes": [
    "legacy_current_manifest_fixtures",
    "identity_comparison_contract",
    "refresh_scheduling_rule"
  ],
  "produces": [
    "legacy_manifest_comparison_proof"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Legacy Manifest Comparison Pattern

## Decision this card owns
Prove semantically equivalent legacy/current manifests compare equal without hiding real identity, compatibility, or provenance changes.

## Use when
- Optional schema differences cause an unnecessary near-full refresh/rewrite despite equivalent approved identity.

## Do not use when
- The difference is an intentional semantic, compatibility, provenance, addition, removal, or value change.

## Required inputs
- Versioned legacy/current fixtures, comparison owner's required identity contract, optional/current metadata rules, real diff/scheduling path, threshold, and migration authority status.

## Procedure
1. Characterize equivalent old/current fixtures and make the real diff/scheduling path RED for the false difference.
2. Separate required identity from optional/current metadata at the comparison owner seam; never rewrite stored source merely to normalize comparison.
3. Preserve true additions, removals, and changes, and keep current-schema behavior/threshold unchanged.
4. Prove the intended legacy fixture becomes GREEN while an intentional semantic delta still schedules work.
5. Test any authorized source migration separately; otherwise keep this pattern read/compare-only.
6. Remove temporary fixtures only after canonical regression coverage; rollback owner-seam normalization rather than mutating legacy evidence.

## Output contract
- Fixture/schema identities, false-diff RED/GREEN, required/optional field decision, real scheduling/threshold outcomes, semantic-delta control, migration authority, cleanup, and rollback evidence.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at comparison proof; never normalize away a real contract/provenance difference or write legacy data without authority.
