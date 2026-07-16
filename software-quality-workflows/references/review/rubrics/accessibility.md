---
{
  "card_id": "sqw.review.rubrics.accessibility",
  "card_version": 1,
  "kind": "rubric",
  "consumes": [
    "rubric_review_contract",
    "bounded_change_material",
    "affected_user_interface"
  ],
  "produces": [
    "accessibility_findings"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Accessibility Rubric

## Decision this card owns
Identify accessibility regressions introduced or materially worsened in the affected interface.

## Use when
- The change affects rendered UI, interaction, content structure, focus, media, or user feedback.

## Do not use when
- No human-facing interface behavior changes or the claim lacks an affected accessible contract.

## Required inputs
- Frozen UI behavior, affected interface states, platform/design-system conventions, available automated/manual evidence, and result-envelope contract.

## Procedure
1. Check keyboard reachability, logical order, visible focus, focus movement/restoration, and escape/cancel behavior.
2. Check native semantics first, accessible names and labels, headings/landmarks, link purpose, alternative text, and control-state exposure.
3. Check announcements for dynamic/error/loading/success states and non-color cues, contrast, zoom/reflow, and motion where relevant.
4. Combine automated checks with risk-matched manual inspection; automation passing is not proof of usable interaction.
5. Emit only reproducible, scoped findings with affected users, failure state, and smallest standards-aligned correction.

## Output contract
- Zero or more local finding candidates with interaction/state, accessible expectation, evidence, user impact, correction, confidence, blocking, and verification.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at accessibility evidence; do not widen into general UI preference or implementation.
