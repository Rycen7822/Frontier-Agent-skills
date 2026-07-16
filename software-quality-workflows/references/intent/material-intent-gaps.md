---
{
  "card_id": "sqw.intent.material-intent-gaps",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "request_sources",
    "repository_defaults",
    "reversibility_evidence"
  ],
  "produces": [
    "intent_gap_classification",
    "default_decisions"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 4096,
  "neighbors": [
    {
      "edge_id": "intent-gaps-to-alternatives",
      "to_card_id": "sqw.intent.design-alternative-selection",
      "edge_mode": "semantic",
      "missing_decision": "Two or more materially different feasible outcomes remain",
      "required_evidence": "Scenario comparison and source constraints",
      "evict_when": "One strategy family or a typed underdetermination result is recorded"
    }
  ]
}
---
# Material Intent Gaps

## Decision this card owns
Classify each missing decision as inferable, safely defaultable, materially ambiguous, conflicting, or externally owned.

## Use when
- Intent assessment has identified unresolved outcome semantics.

## Do not use when
- Only implementation technique is undecided or the failure cause remains unknown.

## Required inputs
- Authoritative request sources, repository facts, affected scenarios, reversibility, and authority limits.

## Procedure
1. List only decisions changing observable outcomes or irreversible commitments; retrieve direct project/source/session facts before requesting user input.
2. Resolve authoritative facts and accept defaults only when explicit, safe, reversible, and low impact.
3. Ask at most one material question at a time when its answer changes design; otherwise state the evidence-backed default and continue.
4. Represent deliberately deferred requirements with stable ID, owner section/path, allowed value shape, authoritative default if any, constraints/source/validation, and `open|resolved|blocked`.
5. Mark conflicts/external decisions without guessing; compare concrete scenarios for multiple feasible meanings.
6. Mark `visual_probe_needed` only for an inherently spatial/visual choice where alternatives aid the user; this does not start runtime tools.
7. Select the alternatives edge only for materially distinct outcomes.

## Output contract
- `resolved_facts`, `safe_defaults`, requirement blocks, `material_ambiguities`, conflicts/external decisions, `visual_probe_needed`, minimum question, and `next_edge_id|null`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `intent-gaps-to-alternatives` | Two or more materially different feasible outcomes remain | Scenario comparison and source constraints | `sqw.intent.design-alternative-selection` | One strategy family or a typed underdetermination result is recorded |

## Stop
Stop when intent is adequate or a typed minimal missing-information result is ready.
