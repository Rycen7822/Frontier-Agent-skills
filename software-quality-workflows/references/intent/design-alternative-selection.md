---
{
  "card_id": "sqw.intent.design-alternative-selection",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "material_ambiguities",
    "scenario_evidence",
    "authority_projection"
  ],
  "produces": [
    "selected_outcome",
    "selection_rationale"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Design Alternative Selection

## Decision this card owns
Select among materially different outcome semantics or prove that current evidence cannot select safely.

## Use when
- At least two feasible outcomes remain after fact and safe-default resolution.

## Do not use when
- Alternatives differ only in internal implementation or a higher authority must choose.

## Required inputs
- Concrete scenarios, constraints, reversibility, compatibility, risk, and source precedence.

## Procedure
1. Include status quo and two or three materially different outcomes when evidence supports them; do not manufacture cosmetic variants.
2. Express scenario outcomes and compare ownership, user value, compatibility/migration, operations, failure modes, safety, reversibility, proof, and rollback.
3. Eliminate alternatives contradicted by authority and lead with the recommended option plus why it best fits inspected constraints.
4. Prefer the smallest reversible option only when semantics remain equivalent; costly/user-visible choices may require the external approval declared by authority.
5. Select one outcome or emit underdetermination with the minimum missing fact.
6. Record rejected alternatives, distinguishing evidence, consequences, proof/rollback boundaries, and any remaining approval decision.

## Output contract
- `selected_outcome|null`, `rejected_alternatives`, `evidence_refs`, `assumptions`, and `underdetermination_certificate|null`.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop after one outcome is justified or safe autonomous continuation is disproved.
