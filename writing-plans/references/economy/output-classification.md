---
{
  "card_id": "wp.economy.output-classification",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "representative_output_baseline",
    "downstream_action_contract",
    "quality_critical_fields"
  ],
  "produces": [
    "output_classification_contract"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 4096,
  "neighbors": [
    {
      "edge_id": "output-to-projection-verification",
      "to_card_id": "wp.economy.projection-and-verification",
      "edge_mode": "hard",
      "hard_predicate_id": "output-class-selected",
      "missing_decision": "Projection and verification policy is not defined",
      "required_evidence": "Field classes, baseline envelope, consumers, and quality anchors",
      "evict_when": "Projection, lazy-load, parity, and measurement gates are fixed"
    }
  ]
}
---
# Output Classification

## Decision this card owns
Classify context/output fields by action value and select result-preserving compact/debug/persisted behavior before optimizing size.

## Use when
- Context replay or agent-facing output economy is itself a requested planning outcome.

## Do not use when
- Ordinary planning only needs a current-node capsule, or size has not been measured on representative envelopes.

## Required inputs
- Representative current outputs/context packs, behavior tests, serialized size/token evidence when available, downstream consumers/actions, and known token sinks.

## Procedure
1. Record source/command/time or artifact identity for the baseline; do not estimate from memory or add tokenizer dependencies merely for product checks.
2. Classify fields as always-visible anchors, compact evidence, debug/full evidence, or persisted state.
3. Protect goal, constraints, phase/checkpoint, validation, next action, blockers, risk/warnings, authority/budget, source/artifact refs, coverage gaps, and required actions.
4. Classify raw traces, full candidate/provenance lists, logs, scoring details, and bulky diagnostics as debug or persisted only when an explicit retrieval path exists.
5. Select compact/default, standard, debug/full, and machine-export classes needed by actual consumers; tiny budgets are smoke tests, never universal defaults.
6. Emit the edge only after field classes and non-negotiable anchors are fixed.

## Output contract
- Baseline identity/size, field-class map, protected anchors, output classes/consumers, token sinks, sensitive fields, and `next_edge_id`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `output-to-projection-verification` | Projection and verification policy is not defined | Field classes, baseline envelope, consumers, and quality anchors | `wp.economy.projection-and-verification` | Projection, lazy-load, parity, and measurement gates are fixed |

## Stop
Stop when every field has an evidence-backed class; never save tokens by hiding required action or failure evidence.
