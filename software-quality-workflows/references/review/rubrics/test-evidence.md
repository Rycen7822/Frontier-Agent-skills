---
{
  "card_id": "sqw.review.rubrics.test-evidence",
  "card_version": 1,
  "kind": "rubric",
  "consumes": [
    "rubric_review_contract",
    "bounded_change_material",
    "verification_evidence"
  ],
  "produces": [
    "test_evidence_findings"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Test Evidence Rubric

## Decision this card owns
Identify whether the scoped change has trustworthy, risk-proportionate behavioral evidence.

## Use when
- Review must judge changed behavior, public contracts, integrations, failures, regressions, or executable documents/notebooks.

## Do not use when
- The task is to design or write tests rather than review submitted evidence.

## Required inputs
- Frozen behavior/risk contract, changed semantic units and boundaries, tests and execution evidence, and result-envelope contract.

## Procedure
1. Map each material changed behavior and risk to evidence at the lowest layer that can prove it without hiding the relevant boundary.
2. Check public contract, integration seams, deterministic error paths, regressions, state transitions, and executable documentation/notebooks where affected.
3. Reject false-green evidence: assertions on mocks instead of outcomes, tests of implementation details, swallowed failures, stale snapshots, skipped cases, or unexercised fixtures.
4. Check determinism, isolation, representative data, and whether the reported command actually collected and ran the intended cases.
5. Emit only concrete coverage or trust defects that could let this change fail undetected, with the smallest additional or corrected evidence.

## Output contract
- Zero or more local finding candidates with uncovered/false-proven risk, evidence, failure mode, correction, confidence, blocking, and verification.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at test-evidence findings; do not implement tests or enter another rubric.
