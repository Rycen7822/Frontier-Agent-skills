---
{
  "card_id": "sqw.review.requirements-traceability",
  "card_version": 1,
  "kind": "rubric",
  "consumes": [
    "stable_requirement_index",
    "frozen_scope_manifest",
    "implementation_evidence",
    "verification_evidence"
  ],
  "produces": [
    "requirements_traceability_artifact"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Requirements Traceability

## Decision this card owns
Build the requirement-to-implementation-to-proof matrix and identify missing, partial, wrong, or unauthorized mappings.

## Use when
- Stable revision-bound requirement/acceptance/migration/observable-contract anchors exist and fidelity is part of the review.

## Do not use when
- Requirements would be inferred from implementation, comments, reviewer preference, or unstable sources.

## Required inputs
- Stable anchor, source revision, scope/exclusions, expected behavior including negative/compatibility cases, implementation paths/contracts, and proof refs.

## Procedure
1. Index every in-scope stable requirement without silently choosing between conflicting sources.
2. Trace each anchor forward to implementation evidence and proportionate proof.
3. Trace each material changed behavior backward to an anchor or necessary bounded support.
4. Classify every row `full`, `partial`, `missing`, or `not_applicable`; unavailable/ambiguous is not not-applicable.
5. Identify wrong mappings and scope creep separately from general engineering quality.
6. Emit ordinary findings for material gaps and a bounded matrix artifact ref for `spec_traceability`.
7. If fidelity is required but sources are unavailable/conflicted, emit inconclusive with minimal missing source; never invent acceptance criteria.

## Output contract
- `requirements_traceability_artifact`: anchor/revision rows, status, implementation/proof refs, gaps, conflicts, coverage summary, and suggested local finding candidates.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop when every stable anchor and material changed behavior is mapped or the exact evidence/source blocker is recorded.
