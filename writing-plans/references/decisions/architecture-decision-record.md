---
{
  "card_id": "wp.decisions.architecture-decision-record",
  "card_version": 1,
  "kind": "decision",
  "consumes": [
    "selected_architecture_decision",
    "alternative_evidence",
    "documentation_authority"
  ],
  "produces": [
    "architecture_decision_record"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Architecture Decision Record

## Decision this card owns
Decide whether a costly durable architecture choice warrants an ADR and emit the minimum proposed/superseding record.

## Use when
- A choice changes public/data/security/runtime/deployment/storage/ownership contracts, has viable alternatives, is costly to reverse, or supersedes an architecture rule.

## Do not use when
- The change is obvious/local/routine/generated, already owned by a more specific artifact, or lacks documentation authority.

## Required inputs
- Selected decision and status, context/constraints/evidence, alternatives, owners/contracts, consequences, proof/rollback, prior ADRs, and project ADR convention.

## Procedure
1. Confirm the trigger and canonical project location; do not create a repository docs convention by ritual.
2. Record title/status, context, exact decision/owners/boundaries/contracts, materially considered alternatives and rejection evidence, consequences/risks/follow-up, verification, and rollback/supersession.
3. Keep detailed evidence in linked artifacts, comment why/invariants rather than obvious code, and synchronize affected API/schema/runbook docs.
4. Never delete historical ADRs; mark supersession/deprecation with lineage.
5. In autonomous closure, candidates may cite but cannot author/accept/publish an ADR. A new record stays proposed until independent SQW review and publication authority pass.

## Output contract
- `adr_required`, canonical location or worknote fallback, proposed ADR identity/status/content, supersession links, proof/rollback, publication owner, and blocker|null.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at the smallest justified proposed ADR or a documented no-ADR decision; never infer publication authority.
