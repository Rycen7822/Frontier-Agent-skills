---
{
  "card_id": "sqw.review.rubrics.product-outcome",
  "card_version": 1,
  "kind": "rubric",
  "consumes": [
    "rubric_review_contract",
    "bounded_change_material",
    "intended_user_outcome"
  ],
  "produces": [
    "product_outcome_findings"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Product Outcome Rubric

## Decision this card owns
Identify whether the scoped change delivers the intended user outcome without breaking important product states.

## Use when
- User-visible behavior, interaction flow, content, or product policy is in scope.

## Do not use when
- The change has no user-observable product contract or the concern belongs to API, accessibility, privacy, or implementation quality.

## Required inputs
- Frozen outcome, affected journeys and dependencies, changed behavior, product/design-system conventions, and result-envelope contract.

## Procedure
1. Trace the intended outcome through entry, success, error, empty, loading, cancellation, and recovery states that the change can reach.
2. Check that behavior, feedback, and state transitions match the frozen requirement and established product conventions.
3. Inspect cross-component dependencies for partial outcomes, stale state, misleading success, or irreversible user actions.
4. Require behavior-level evidence proportionate to user impact; do not substitute implementation shape or screenshots alone for the outcome.
5. Emit only regressions introduced or materially worsened by this change, with the smallest viable correction.

## Output contract
- Zero or more local finding candidates with affected journey/state, expected and observed outcome, evidence, impact, correction, confidence, blocking, and verification.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at product-outcome evidence; do not expand scope or enter implementation.
