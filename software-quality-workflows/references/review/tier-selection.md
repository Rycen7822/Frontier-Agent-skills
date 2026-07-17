---
{
  "card_id": "sqw.review.tier-selection",
  "card_version": 2,
  "kind": "decision",
  "decision_id": "sqw.select.review.tier-selection",
  "required_artifact_ids": [],
  "produced_artifact_ids": [
    "review-tier"
  ],
  "max_bytes": 4096
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
6. Emit `review-tier` with tier, independence need, bounded input requirement, cycle budget, implicated rubric decision IDs, and blocker; Router owns every continuation.

## Output contract
- One `review-tier`: tier, reason codes, scope depth, independence, rubric decision IDs, fix-cycle budget, required input, and blocker.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at the tier artifact. R0 returns to its owner; Router selects only mapped decisions whose prerequisites are ready.
