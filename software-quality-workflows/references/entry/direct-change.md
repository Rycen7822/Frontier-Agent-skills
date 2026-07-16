---
{
  "card_id": "sqw.entry.direct-change",
  "card_version": 1,
  "kind": "entry",
  "consumes": [
    "request_mode",
    "intent_status",
    "root_cause_status",
    "authority_projection",
    "scope_projection"
  ],
  "produces": [
    "change_contract",
    "proof_need"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 4096,
  "neighbors": [
    {
      "edge_id": "direct-to-owner-seam",
      "to_card_id": "sqw.change.local-change-boundary",
      "edge_mode": "semantic",
      "missing_decision": "Owner unresolved",
      "required_evidence": "Owner evidence",
      "evict_when": "Boundary set"
    },
    {
      "edge_id": "direct-to-behavior-distinction",
      "to_card_id": "sqw.test.behavior-distinction-and-red",
      "edge_mode": "semantic",
      "missing_decision": "Oracle nondiscriminating",
      "required_evidence": "Oracle evidence",
      "evict_when": "Distinction set"
    },
    {
      "edge_id": "direct-to-gate-selection",
      "to_card_id": "sqw.verify.gate-selection",
      "edge_mode": "semantic",
      "missing_decision": "Proof unresolved",
      "required_evidence": "Gate evidence",
      "evict_when": "Proof plan set"
    },
    {
      "edge_id": "direct-to-api-contract",
      "to_card_id": "sqw.domain.api.contract-change",
      "edge_mode": "hard",
      "hard_predicate_id": "public-contract-implicated",
      "missing_decision": "Compatibility unresolved",
      "required_evidence": "Contract evidence",
      "evict_when": "Compatibility set"
    }
  ]
}
---
# Direct Change

## Decision this card owns
Form the smallest authorized standard-change contract and select at most one unresolved decision.

## Use when
- Authorized M0 or standard-plan/candidate frontier with adequate intent, known/inapplicable cause, and no autonomous closure.

## Do not use when
- Cause unknown, intent underdefined, request read-only, recovery active, or Admission pending.

## Required inputs
- Outcome; source/scope/authority/effect; protected work; owner/proof evidence; patch; implicated surfaces.

## Procedure
1. Bind source/outcome, writes/effects, protected and dirty/concurrent work, publication ceiling, and cleanup.
2. State the before/after distinction; for bugs bind supported cause and original RED. If no oracle distinguishes outcomes, request RED.
3. Trace caller to outcome and choose the narrowest coherent owner seam; request boundary only if evidence cannot defend one.
4. Define the smallest general patch; reject parallel code, speculative seams, unrelated cleanup, and candidate-protected writes.
5. Emit implicated-surface facts. Public uncertainty uses the API edge; other domain decisions reroute after this artifact.
6. Select focused and smallest affected/public proof, or request gate selection. Downstream proof preserves status and failure class.
7. Require diff/generated/dependency/temp/protected inspection, review/residual-risk facts, and not-run/blocked proof; growth invalidates completion.
8. Send durable/migration/multi-owner/architecture scope to planning; workers propose source-bound plan changes, never rewrite canonical state.

## Output contract
- `change_contract`: identities, seam, distinction, surfaces, patch preservation, proof/checks, review/plan facts, `next_edge_id|null`, `blocker|null`.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `direct-to-owner-seam` | Owner unresolved | Owner evidence | `sqw.change.local-change-boundary` | Boundary set |
| `direct-to-behavior-distinction` | Oracle nondiscriminating | Oracle evidence | `sqw.test.behavior-distinction-and-red` | Distinction set |
| `direct-to-gate-selection` | Proof unresolved | Gate evidence | `sqw.verify.gate-selection` | Proof plan set |
| `direct-to-api-contract` | Compatibility unresolved | Contract evidence | `sqw.domain.api.contract-change` | Compatibility set |

## Stop
Stop at contract/blocker. Executor implements; other owners prove/close. Never promote, close workflow state, or publish.
