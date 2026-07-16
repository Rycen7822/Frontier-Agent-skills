---
{
  "card_id": "sqw.review.review-execution",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "review_tier_decision",
    "frozen_scope_manifest",
    "bounded_review_material",
    "rubric_assignment_projection"
  ],
  "produces": [
    "review_execution_artifacts"
  ],
  "max_active_neighbors": 1,
  "max_bytes": 8192,
  "neighbors": [
    {
      "edge_id": "review-to-requirements",
      "to_card_id": "sqw.review.requirements-traceability",
      "edge_mode": "hard",
      "hard_predicate_id": "stable-requirements-available",
      "missing_decision": "Stable requirements exist and traceability is incomplete",
      "required_evidence": "Requirement IDs and frozen scope",
      "evict_when": "Traceability artifact recorded"
    }
  ]
}
---
# Review Execution

## Decision this card owns
Execute one bounded local review while preserving scope, reviewer/fixer separation, independent rubric slices, and honest coverage.

## Use when
- R1/R2 tier is selected and a revision-addressed scope/material projection is ready.

## Do not use when
- Scope is unfrozen, review authority is absent, or only R0 self-diff closeout is required.

## Required inputs
- Tier/cycle budget, frozen base/head/scope/path snapshots, bounded diff/owner context, exclusions, verification index, stable requirements if any, and one rubric assignment per specialist reviewer.

## Procedure
1. Validate manifest identity and include added/modified/deleted/renamed/untracked plus generated/vendor/binary classifications.
2. Review the scoped diff and enough owning context for behavior, compatibility, data flow, and local rules.
3. Record each path as full, sampled with boundary, or not reviewed; truncation is never full.
4. Load requirements only through the declared edge. Router assigns each other implicated rubric as an independent primary; no reviewer traverses other rubrics.
5. Give reviewers shared short authority/scope/result contracts plus only their rubric and bounded material. Never give reviewer a fixer contract or intended answer.
6. Contextualize scanner/tool output, coalesce duplicate root causes, and preserve positive evidence.
7. Re-observe head/scope, validate findings and coverage, and stop at tier cycle budget. Fixes require separately authorized disposition and proof.
8. Emit execution artifacts; Router later selects result-envelope. Hosted publication remains separate.

## Output contract
- `review_execution_artifacts`: bound scope/coverage, candidate findings by rubric, traceability ref|null, evidence index, positive notes, reviewer independence/limits, cycle use, stale/blocker state.

## Load next only if

| Edge ID | Missing decision | Required evidence | Next card | Evict when |
|---|---|---|---|---|
| `review-to-requirements` | Stable requirements exist and traceability is incomplete | Requirement IDs and frozen scope | `sqw.review.requirements-traceability` | Traceability artifact recorded |

## Stop
Stop on stale scope, invalid output after one same-scope retry, cycle exhaustion, or completed evidence fan-in; do not fix or publish.
