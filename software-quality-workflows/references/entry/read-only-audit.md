---
{
  "card_id": "sqw.entry.read-only-audit",
  "card_version": 2,
  "kind": "decision",
  "decision_id": "sqw.select.entry.read-only-audit",
  "required_artifact_ids": [],
  "produced_artifact_ids": [
    "workflow-intake"
  ],
  "max_bytes": 4096
}
---
# Read-Only Audit Entry

## Decision this card owns
Freeze an evidence-bound audit intake while preserving read-only authority.

## Use when
- The requested outcome is findings, review, explanation, status, or evidence rather than edits.

## Do not use when
- Implementation or an isolated stateful diagnostic probe is the authorized primary outcome.

## Required inputs
- Audit question, immutable source/scope identity, exclusions, architecture/product/runtime/config surfaces, coverage requirement, and available evidence.

## Procedure
1. Freeze the reviewed identity, audit question, scope, exclusions, and read-only authority.
2. Build a coverage matrix across relevant interfaces, state/data flows, runtime/config/deployment, integrations, trust boundaries, failures, tests, and docs; mark each full, sampled, or not reviewed.
3. Corroborate architecture claims from executable sources and trace representative end-to-end flows, ownership, invariants, failure propagation, recovery, and observability.
4. Bind findings to revision-stable evidence, affected surface, severity/impact, confidence, and violated contract; separate defects, risks, questions, and observations.
5. Preserve read-only authority across every slice and reconcile overlap, conflicts, and unreviewed gaps.
6. Emit `workflow-intake` plus a typed request only for a mapped review/evidence decision; never mutate, format, stage, or generate target files.

## Output contract
- One `workflow-intake` with source/scope, coverage contract, architecture map, findings classes, evidence refs, not-reviewed items, residual risk, blocker, and optional typed decision request.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop with an evidence-bound result; never convert the audit into edits.
