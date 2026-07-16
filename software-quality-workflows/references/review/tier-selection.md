---
{
  "card_id": "sqw.review.tier-selection",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "review_request",
    "scope_projection",
    "risk_surface_projection",
    "authority_projection"
  ],
  "produces": [
    "review_tier_decision"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 4096,
  "neighbors": [
    {
      "edge_id": "review-tier-to-execution",
      "to_card_id": "sqw.review.review-execution",
      "edge_mode": "hard",
      "hard_predicate_id": "bounded-review-input-ready",
      "missing_decision": "R1/R2 tier selected with bounded review input",
      "required_evidence": "Frozen scope and risk evidence",
      "evict_when": "Execution contract recorded"
    }
  ]
}
---
# Review Tier Selection

## Decision this card owns
Choose the smallest R0/R1/R2 review tier that can answer the requested local technical question safely.

## Use when
- Request mode is review and tier, independence, scope depth, or fix-cycle budget is unresolved.

## Do not use when
- The request is a general report/audit, or a fresh tier decision already binds the same scope and risk surfaces.

## Required inputs
- Review outcome, authority, frozen-scope readiness, changed/implicated surfaces, plausible impact, repository rules, available independent context, and fix authorization.

## Procedure
1. Select R0 for routine M0 closeout/focused blocker inspection: implementer self-diff, owner context, focused evidence, zero automatic independent reviewer.
2. Select R1 for substantive owner/cross-component/M2 work: full scoped diff, relevant call sites, specification axis when applicable, engineering axis, and at most one authorized focused fix cycle.
3. Select R2 for security, data loss, public contract, migration, release, broad refactor, or explicit high risk: independent complete declared-scope review, only triggered specialist surfaces, and at most two explicitly justified fix cycles.
4. Review-only always has zero fix budget. Reviewer availability never widens authority; absence is an evidence limit.
5. Record exactly which rubric surfaces are implicated without loading them into this decision.
6. Emit tier, independence need, bounded input requirement, cycle budget, and blocker.

## Output contract
- `review_tier_decision`: tier, reason codes, scope depth, independence, rubric surface IDs, fix-cycle budget, required input, `next_edge_id|null`, blocker.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `review-tier-to-execution` | R1/R2 tier selected with bounded review input | Frozen scope and risk evidence | `sqw.review.review-execution` | Execution contract recorded |

## Stop
Stop at the tier artifact. R0 may return to its owner; R1/R2 load execution only after bounded input is ready.
