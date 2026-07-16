---
{
  "card_id": "sqw.test.lifecycle-change-and-retirement",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "test_classification_and_provenance",
    "authorized_lifecycle_action",
    "replacement_and_gate_evidence"
  ],
  "produces": [
    "test_lifecycle_transition_artifact"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Test Lifecycle Change and Retirement

## Decision this card owns
Execute and prove an authorized keep, merge, update, promote, quarantine, supersede, retire, or suite-boundary decision without silently weakening protection.

## Use when
- Classification is complete and at least one test needs a lifecycle, oracle, ownership, gate, replacement, or suite-boundary change.

## Do not use when
- The test's meaning is unclassified, product/requirement authority is unresolved, or the task is merely to create a behavior RED/GREEN.

## Required inputs
- Classification artifact, authorized action, current/changed requirement, old and replacement oracles, transition/confirmation evidence, owner/review trigger, affected gates, and edit scope.

## Procedure
1. Choose deliberately: keep unique current protection; merge only with equal oracle/localization; update for a changed valid contract; promote when scaffold/characterization becomes durable evidence.
2. Quarantine visibly only for a still-required but unreliable/unavailable test; record signature, reproducibility, environments, gate treatment, owner, repair criterion, and forced review event.
3. Supersede only with equal/stronger replacement plus confirmation gate/window; its trigger must retire the old test or restore it to active, never become hidden indefinite quarantine.
4. Retire only after the requirement/risk is removed or an approved proven replacement makes it irrelevant. Age, runtime, duplication appearance, or failure under a new implementation is insufficient.
5. For requirement changes, search anchors/behavior across tests, fixtures, scripts, and gate config; classify all hits and prove replacement coverage before removal.
6. For suite moves, preserve observable oracles at the cheapest sufficient layer and preserve/update an explicit project gate; a familiar command must not silently prove less.
7. Apply only authorized edits, run transition and affected-gate proof, then record changed classifications, replacements, gate status, cleanup, deferred decisions, and residual limits.

## Output contract
- Test/action inventory; before/after lifecycle and location; authority/requirement refs; replacement and confirmation proof; owner/review trigger; gate diffs/status; retained protection; cleanup; blockers and deferred product decisions.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop after the authorized transition and proof. Never rewrite a still-valid contract merely to make a new implementation pass.
