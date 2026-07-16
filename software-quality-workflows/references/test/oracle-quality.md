---
{
  "card_id": "sqw.test.oracle-quality",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "distinction_contract",
    "test_source",
    "implementation_source",
    "oracle_provenance"
  ],
  "produces": [
    "oracle_quality_decision"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Oracle Quality

## Decision this card owns
Decide whether a test oracle is independent, sensitive to realistic defects, and faithful to the behavior boundary rather than the implementation shape.

## Use when
- A test could pass through shared logic, regenerated goldens, weak round trips, excessive mocking, fixture overfit, or private-call assertions.

## Do not use when
- Oracle provenance and mutation/sensitivity evidence already establish that the test rejects the relevant wrong outcomes.

## Required inputs
- Behavior distinction, test and implementation source, expected-value provenance, doubles/fixtures, plausible wrong implementations, and focused results.

## Procedure
1. Trace expected values to a requirement, literal worked example, independently implemented reference, stable external fixture, or property/metamorphic relation.
2. Reject expected values computed by the production helper, generator, parser, or the same algorithm under another name.
3. Name and, when proportionate, inject or simulate at least one plausible wrong implementation that the assertion must kill.
4. For round trips, add an independent property or fixed expectation when encoder and decoder could share a defect.
5. Use real collaborators by default. Allow doubles only at nondeterministic, expensive, destructive, unavailable, or genuinely external boundaries, with a narrower explicit contract.
6. Prefer public behavior over private call order; cover contract-owned errors, limits, transitions, and negative paths.
7. For serialization or migration, require an externally meaningful fixed fixture or cross-implementation expectation, not only newly generated goldens.

## Output contract
- `oracle_quality_decision`: `adequate|needs_repair|inconclusive`, provenance refs, wrong implementations killed, double boundaries, uncovered false-green risks, and required repair.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop a completion claim when the oracle can agree with a plausible wrong implementation or derive expected behavior from the production path it is meant to verify.
