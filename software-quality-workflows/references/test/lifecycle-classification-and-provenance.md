---
{
  "card_id": "sqw.test.lifecycle-classification-and-provenance",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "touched_test_inventory",
    "requirement_risk_anchors",
    "test_gate_inventory"
  ],
  "produces": [
    "test_classification_and_provenance"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 4096,
  "neighbors": [
    {
      "edge_id": "test-lifecycle-to-change",
      "to_card_id": "sqw.test.lifecycle-change-and-retirement",
      "edge_mode": "hard",
      "hard_predicate_id": "test-lifecycle-action-classified",
      "missing_decision": "Test meaning is classified but its lifecycle action is unresolved",
      "required_evidence": "Purpose, layer, lifecycle, anchor, owner, gate, and proposed action",
      "evict_when": "Lifecycle action and transition proof recorded"
    }
  ]
}
---
# Test Lifecycle Classification and Provenance

## Decision this card owns
Classify what each touched durable test protects, where it proves it, its current lifecycle, and the provenance needed to audit that meaning.

## Use when
- Tests are added, changed, moved, merged, quarantined, promoted, superseded, retired, or audited.

## Do not use when
- Only implementation behavior or gate execution changes and no test's meaning, location, status, or retention is in question.

## Required inputs
- Touched/related test inventory, requirement/bug/contract/risk anchors, current gates, repository metadata conventions, and known replacement/transition evidence.

## Procedure
1. Classify purpose independently as `requirement`, `regression`, `characterization`, `migration`, `adversarial`, or `smoke`.
2. Classify layer independently as `unit`, `component`, `integration`, `end_to_end`, `installed_surface`, or `external_system`.
3. Record lifecycle as `active`, `quarantined`, `superseded`, or `retired`; do not infer it from age, location, runtime, or current failure.
4. Make anchor, purpose, layer, lifecycle, owner, and canonical gate discoverable using the project's lightest searchable convention.
5. For non-active tests record transition evidence; for superseded/retired replacement record replacement anchor; for quarantined/superseded record an exit/review trigger.
6. Inventory ambiguous, duplicate, brittle, omitted-from-gate, or unowned tests without changing their lifecycle by reviewer preference.

## Output contract
- Per-test identity, purpose, layer, lifecycle, requirement/risk anchor, owner, canonical gate, replacement/transition refs, review trigger, ambiguity, and proposed action or `keep`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `test-lifecycle-to-change` | Test meaning is classified but its lifecycle action is unresolved | Purpose, layer, lifecycle, anchor, owner, gate, and proposed action | `sqw.test.lifecycle-change-and-retirement` | Lifecycle action and transition proof recorded |

## Stop
Stop after classification/provenance. Do not edit, quarantine, weaken, move, or retire a test in this card.
