---
{
  "card_id": "wp.closure.search-and-publication-policy",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "draft_closure_contract",
    "authority_projection",
    "cost_side_effect_evidence"
  ],
  "produces": [
    "search_publication_contract"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Search and Publication Policy

## Decision this card owns
Freeze admissible strategy/search, resource/stop rules, side effects, and the independent publication ceiling.

## Use when
- Autonomous closure strategy families, budgets, stop behavior, or publication authority are unresolved.

## Do not use when
- The request is standard execution or another closure section is the only gap.

## Required inputs
- Admission and authority ceiling; admitted strategy evidence; resource/cost/environment limits; hard/soft objectives; side-effect and publication policy.

## Procedure
1. Name admitted strategy families and the evidence/objective each can affect; candidates cannot silently add a family.
2. Set candidate, attempt, wall-time, compute, storage, network, and external-cost budgets plus bounded retry/idempotency rules.
3. Define deterministic comparison order, stop/non-convergence rules, incumbent retention, and escalation behavior after hard constraints pass.
4. Bound local/external effects and protected resources. The contract may narrow but never widen Admission authority.
5. Treat merge, push, release, deploy, publication, and other remote writes as separate gates; acceptance never implies them.
6. Emit an authority/environment blocker when an essential search or proof action is unavailable rather than fabricating feasibility.

## Output contract
- Strategy families, budgets, comparison/stop/incumbent policy, retry/effect boundaries, publication ceiling, and `blocker|null`.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop only when search and publication decisions are deterministic and within bound authority.
