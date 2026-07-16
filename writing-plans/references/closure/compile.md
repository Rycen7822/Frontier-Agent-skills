---
{
  "card_id": "wp.closure.compile",
  "card_version": 1,
  "kind": "entry",
  "consumes": [
    "closure_admission_projection",
    "request_source_projection",
    "authority_projection",
    "repository_evidence_projection"
  ],
  "produces": [
    "draft_closure_contract",
    "compiler_certificate"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 4096,
  "neighbors": [
    {
      "edge_id": "compile-to-constraints-corners",
      "to_card_id": "wp.closure.hard-constraints-and-corners",
      "edge_mode": "semantic",
      "missing_decision": "Constraints or corners are incomplete",
      "required_evidence": "Acceptance/runtime evidence",
      "evict_when": "IDs, oracles, and corners are fixed"
    },
    {
      "edge_id": "compile-to-assumptions-ambiguity",
      "to_card_id": "wp.closure.assumptions-and-ambiguity",
      "edge_mode": "semantic",
      "missing_decision": "Unsafe semantic ambiguity remains",
      "required_evidence": "Source conflict/alternative evidence",
      "evict_when": "Assumptions or certificate fixed"
    },
    {
      "edge_id": "compile-to-search-publication",
      "to_card_id": "wp.closure.search-and-publication-policy",
      "edge_mode": "semantic",
      "missing_decision": "Search or publication policy is unresolved",
      "required_evidence": "Authority/cost/side-effect evidence",
      "evict_when": "Policy fixed"
    },
    {
      "edge_id": "compile-to-freeze-handoff",
      "to_card_id": "wp.closure.freeze-and-handoff",
      "edge_mode": "hard",
      "hard_predicate_id": "closure-contract-sections-complete",
      "missing_decision": "Complete draft is not frozen",
      "required_evidence": "Validated draft and identities",
      "evict_when": "Frozen handoff emitted"
    }
  ]
}
---
# Compile Closure Contract

## Decision this card owns
Compile an admitted request into a complete draft or typed certificate.

## Use when
- `CLOSURE_ELIGIBLE` exists and no matching frozen contract exists.

## Do not use when
- Admission is not eligible, a matching contract exists, or another epoch executes.

## Required inputs
- Admission, source evidence, identities, verifier feasibility, and budget/publication ceilings.

## Procedure
1. Resolve source precedence/contradictions; invent no requirement.
2. Compile stable executable hard-constraint and material-corner IDs.
3. Record source-bound assumptions and only provably safe defaults.
4. Define independent verifier requirements candidates cannot weaken.
5. Order soft objectives lexicographically with deterministic ties.
6. Bound strategy, retry, cost, resource, side-effect, stop, and publication policy.
7. Validate all sections and exact Admission/source/scope/bundle/authority/environment bindings.
8. Emit the draft or minimal underdetermination/unsat/blocker certificate; create no SQW state.

## Output contract
- Bound draft ref, missing/assumption records, ambiguity/unsat certificates, and `next_edge_id|null`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `compile-to-constraints-corners` | Constraints or corners are incomplete | Acceptance/runtime evidence | `wp.closure.hard-constraints-and-corners` | IDs, oracles, and corners are fixed |
| `compile-to-assumptions-ambiguity` | Unsafe semantic ambiguity remains | Source conflict/alternative evidence | `wp.closure.assumptions-and-ambiguity` | Assumptions or certificate fixed |
| `compile-to-search-publication` | Search or publication policy is unresolved | Authority/cost/side-effect evidence | `wp.closure.search-and-publication-policy` | Policy fixed |
| `compile-to-freeze-handoff` | Complete draft is not frozen | Validated draft and identities | `wp.closure.freeze-and-handoff` | Frozen handoff emitted |

## Stop
Stop on a complete draft or typed certificate/blocker; freeze and SQW execution remain separate.
