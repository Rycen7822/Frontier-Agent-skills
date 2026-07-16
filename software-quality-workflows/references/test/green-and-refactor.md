---
{
  "card_id": "sqw.test.green-and-refactor",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "distinction_contract",
    "red_evidence",
    "change_contract",
    "source_identity"
  ],
  "produces": [
    "green_evidence",
    "refactor_record"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 4096,
  "neighbors": [
    {
      "edge_id": "green-to-oracle-quality",
      "to_card_id": "sqw.test.oracle-quality",
      "edge_mode": "semantic",
      "missing_decision": "The passing test may be tautological, overfit, or unable to reject a plausible wrong implementation",
      "required_evidence": "Test/implementation diff, oracle provenance, and focused result",
      "evict_when": "Oracle sensitivity and independence are recorded"
    }
  ]
}
---
# GREEN and Refactor

## Decision this card owns
Implement the smallest general change that satisfies the current behavior contract, then improve structure only while proof stays green.

## Use when
- A valid RED or explicitly bounded before/after characterization exists and the authorized change contract is ready.

## Do not use when
- Root cause, material intent, public contract, owner seam, or implementation authority is unresolved.

## Required inputs
- Behavior and distinction contracts, RED/characterization evidence, authorized owner seam and change surface, protected work, and focused gate command.

## Procedure
1. Change the real owning seam, including contract-internal edge cases, without adding behavior outside the current contract.
2. Prefer a general contract implementation over fixture constants, wrappers, caches, modes, adapters, dependencies, or parallel paths that merely bypass the defect.
3. Run the focused test after each coherent patch and preserve unrelated, user, and predecessor work.
4. If GREEN requires a new public behavior, schema, dependency, mode, architecture, or owner decision, stop and return to planning rather than widening scope.
5. After GREEN, remove duplication, improve names/boundaries, simplify setup/assertions, and extract helpers only when repeated evidence warrants them.
6. Refactor in small steps while the focused proof remains green; do not delete working code just to manufacture an ideal historical TDD sequence.
7. Classify conflicts with old tests as still-valid contract, intentionally changed contract, stale implementation detail, genuine regression, or harness/environment failure before changing either side.
8. Emit GREEN and refactor evidence, then let the verification owner select affected/public/canonical gates.

## Output contract
- `green_evidence`: implementation boundary, focused result, source/scope identity, and contract coverage.
- `refactor_record`: structural changes after GREEN, preserved behavior, and any unplanned decision blocker.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `green-to-oracle-quality` | The passing test may be tautological, overfit, or unable to reject a plausible wrong implementation | Test/implementation diff, oracle provenance, and focused result | `sqw.test.oracle-quality` | Oracle sensitivity and independence are recorded |

## Stop
Stop when focused GREEN is general and refactoring remains proven, or return a typed planning/authority blocker before expanding the contract.
