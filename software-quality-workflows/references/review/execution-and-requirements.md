# Review Execution and Requirements

## Purpose
Execute one bounded independent review and trace stable requirements to implementation and proof without inventing criteria.

## Use when
- R1/R2 is selected with frozen material, or stable requirements make fidelity part of the review.

## Do not use when
- Scope is unfrozen, review authority is absent, or R0 self-diff closeout is sufficient.

## Required inputs
- `review-tier`; cycle budget; frozen base/head/scope/path snapshots; diff and owner context; exclusions; verification index; stable requirement anchors when applicable; and one bounded rubric assignment per specialist.

## Procedure
1. Validate identity and classify added, modified, deleted, renamed, untracked, generated, vendor, and binary paths.
2. Review the full scoped diff plus enough owning context for behavior, compatibility, data flow, and local rules. Mark every path full, sampled with boundary, or not reviewed; truncation is never full.
3. Give each independent reviewer shared short scope/authority/result contracts plus one rubric and bounded material. Reviewer/fixer separation is mandatory; no reviewer traverses siblings or receives the intended answer.
4. Contextualize scanner/tool candidates, coalesce duplicate root causes, preserve positive evidence, and stop at the tier cycle budget.
5. When stable requirements exist, index every in-scope anchor without choosing between conflicts. Trace each forward to implementation/proof and each material changed behavior backward to an anchor or necessary bounded support.
6. Classify trace rows full, partial, missing, or not-applicable; unavailable/ambiguous is not not-applicable. Separate wrong mappings and scope creep from engineering quality and never invent acceptance criteria.
7. Re-observe head/scope and validate finding candidates, coverage, rubric independence, and traceability. One same-scope retry may repair malformed review output, not substantive disagreement.
8. Emit execution/traceability artifacts only; fixes require separately authorized finding disposition and hosted publication remains separate.

## Required result
- One `review-execution` with bound identity/scope/coverage, finding candidates by rubric, requirement→implementation→proof matrix and conflicts/gaps, evidence index, positive notes, reviewer independence/limits, cycle use, stale state, and blocker.

## Stop
Stop on stale scope, cycle exhaustion, missing authoritative requirements, or complete evidence fan-in; do not fix or publish.
