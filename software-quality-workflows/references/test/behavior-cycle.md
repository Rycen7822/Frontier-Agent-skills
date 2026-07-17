---
{
  "card_id": "sqw.test.behavior-cycle",
  "card_version": 2,
  "kind": "procedure",
  "decision_id": "sqw.select.test.behavior-cycle",
  "required_artifact_ids": [
    "workflow-intake"
  ],
  "produced_artifact_ids": [
    "test-behavior-cycle"
  ],
  "max_bytes": 8192
}
---
# Behavior Test Cycle

## Decision this card owns
Establish a valid behavior distinction and RED, implement the smallest general repair, then refactor only under GREEN proof.

## Use when
- Authorized behavior will change and no fresh independent before/after evidence covers the current source and owner seam.

## Do not use when
- Intent, cause, public contract, owner seam, or implementation authority is unresolved; or the edit is documentation-only.

## Required inputs
- `workflow-intake`; behavior/non-goals/compatibility contract; current behavior; independent oracle source; real owner path; protected work; authorized surface; and focused gate.

## Procedure
1. State trigger/input, expected output/state transition, boundary/error behavior, non-goals, and compatibility before choosing a test shape.
2. Select one behavior-complete vertical slice through the real owner path and an oracle derived from a requirement, worked literal, independent reference, fixed cross-version fixture, or property/metamorphic relation.
3. Name a plausible wrong implementation the assertion kills; add an independent check when both sides of a round trip could share one defect.
4. Run the smallest real test/probe before production changes. Accept RED only when the intended surface is reached and behavior is absent/wrong; syntax, import, setup, fixture, permission, harness, and unavailable environment failures are not RED.
5. If the test passes, distinguish existing behavior, weak assertion, and wrong surface. When strict automated RED is impossible, preserve characterization and the exact evidence limitation.
6. Preserve existing patches and valid old contracts. Change the real owner seam with the smallest general implementation; reject fixture constants, bypass wrappers, speculative caches/modes/adapters/dependencies, and parallel paths.
7. Run focused proof after each coherent patch. Stop for planning when GREEN requires an unapproved public behavior, schema, dependency, architecture, mode, or owner change.
8. After GREEN, remove duplication and simplify names/boundaries/setup only in small proven steps. Do not rewrite history or delete valid work to manufacture idealized TDD.
9. Classify conflicts with old tests as valid contract, intentional contract change, stale implementation detail, regression, harness, or environment before changing either side.

## Output contract
- One `test-behavior-cycle` with distinction, vertical slice, oracle/provenance, wrong implementation killed, RED or limitation evidence, implementation boundary, focused GREEN, refactor record, preserved contracts/work, source/scope/environment identity, and blocker.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at general focused GREEN with proven refactoring, or at a typed evidence/planning/authority blocker.
