---
{
  "card_id": "sqw.review.rubrics.architecture-maintainability",
  "card_version": 1,
  "kind": "rubric",
  "consumes": [
    "rubric_review_contract",
    "bounded_change_material",
    "repository_conventions"
  ],
  "produces": [
    "architecture_maintainability_findings"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Architecture and Maintainability Rubric

## Decision this card owns
Identify actionable architecture/maintainability regressions introduced or materially worsened by the scoped change.

## Use when
- Changed ownership seams, high-churn logic, broad call-site impact, or explicit smell/refactor review triggers this rubric.

## Do not use when
- The issue is mechanical formatting/lint, unrelated debt, product scope, missing specification, or a security/performance claim.

## Required inputs
- Frozen scope, changed semantic units and callers, local architecture/conventions, evidence, and result-envelope contract.

## Procedure
1. Read enough context for ownership/data flow; local intentional architecture outranks generic heuristics.
2. Check names/responsibilities, duplicated policy, feature envy/data clumps/primitives, repeated dispatch, shotgun/divergent change, speculative generality, message chains, pass-through middlemen, and refused contracts.
3. Ask whether this change introduced/worsened the issue and name concrete drift/change cost.
4. Prefer smallest rename/extract/inline/move-to-owner/deletion; do not prescribe broad redesign without evidence.
5. Emit only contextual line-grounded findings with independent severity/blocking, or useful positive notes; never manufacture a smell.

## Output contract
- Zero or more local finding candidates with category, evidence, maintenance impact, smallest correction, confidence, blocking, verification, and positive notes.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at scoped maintainability evidence; do not enter architecture implementation or another rubric.
