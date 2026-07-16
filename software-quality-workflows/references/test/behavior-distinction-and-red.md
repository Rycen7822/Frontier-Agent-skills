---
{
  "card_id": "sqw.test.behavior-distinction-and-red",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "behavior_contract",
    "existing_oracles",
    "source_identity"
  ],
  "produces": [
    "distinction_contract",
    "red_evidence"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Behavior Distinction and RED

## Decision this card owns
Define and execute the smallest independent oracle that distinguishes the required behavior from the current behavior.

## Use when
- Behavior will change and current proof cannot distinguish old from new outcomes.

## Do not use when
- The edit is documentation-only, or an existing independent oracle already proves the distinction.

## Required inputs
- User-observable contract, explicit non-goals/compatibility constraints, current behavior, independent expected source, runnable boundary, and lifecycle provenance for any changed test.

## Procedure
1. State input/trigger, expected output or state transition, boundary/error behavior, non-goals, and compatibility constraints before choosing test shape.
2. Select one behavior-complete vertical slice through the real owner path; do not prebuild disconnected tests or layers.
3. Select an oracle independent of production helpers: requirement, worked literal, independent reference, fixed cross-version fixture, or property/metamorphic relation.
4. Name a plausible wrong implementation the assertion would kill; round trips need a second check when both directions can share one defect.
5. Run the smallest test or repeatable probe before production changes. It must reach the intended surface and fail because behavior is absent or wrong.
6. Reject syntax, import, fixture, unavailable-environment, and invented-helper failures as RED; repair/classify the harness before implementation.
7. If the test passes immediately, determine whether behavior exists, the assertion is weak, or the wrong surface ran.
8. Preserve existing patches and valid old contracts. When automated RED is impossible, record characterization and the exact evidence limitation without claiming strict TDD.
9. Bind RED or limitation evidence to source, scope, environment, distinction, and test provenance.

## Output contract
- `distinction`, `vertical_slice`, `oracle`, `wrong_implementation_killed`, `red_status`, `evidence_ref`, `test_provenance`, and `blocker|null`.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop after a valid RED or an honestly classified evidence limitation is recorded.
