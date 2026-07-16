---
{
  "card_id": "sqw.test.patterns.cross-language-parity",
  "card_version": 1,
  "kind": "recipe",
  "consumes": [
    "cross_language_public_contract",
    "versioned_data_fixture",
    "allowed_platform_differences"
  ],
  "produces": [
    "cross_language_parity_proof"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Cross-Language Parity Pattern

## Decision this card owns
Prove equivalent observable behavior across language implementations without erasing intentional platform semantics or coupling one runtime to another.

## Use when
- Extraction, rewrite, or consolidation must preserve one contract across two or more language implementations.

## Do not use when
- Contracts intentionally differ or a shared fixture would hide legitimate platform-specific behavior.

## Required inputs
- Characterized public behavior for every implementation, versioned data-only fixture/schema, errors, normalization rule, and predeclared allowed differences.

## Procedure
1. Inventory public behavior in each implementation and encode inputs, outputs, error cases, and schema version in a data-only fixture.
2. Load/execute the fixture natively in each language; never route one implementation through another merely to claim parity.
3. Add a behavior RED in each implementation for the changed gap, then refactor language-local helpers/callers in bounded slices.
4. Record intentional platform differences explicitly outside fixture execution code.
5. Run focused native tests and affected public surfaces; compare serialized outcomes/errors under the canonical normalization rule.
6. Keep the prior implementation until parity and allowed differences are proven; clean only task-owned generated fixtures/wiring.

## Output contract
- Fixture/schema revision, per-language command/status evidence, normalized outcome/error comparison, allowed differences, public-surface coverage, rollback state, and cleanup.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at cross-language evidence; do not redefine parity to hide a regression.
