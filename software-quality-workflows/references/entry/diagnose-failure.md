---
{
  "card_id": "sqw.entry.diagnose-failure",
  "card_version": 2,
  "kind": "decision",
  "decision_id": "sqw.select.entry.diagnose-failure",
  "required_artifact_ids": [],
  "produced_artifact_ids": [
    "workflow-intake"
  ],
  "max_bytes": 4096
}
---
# Diagnose Failure Entry

## Decision this card owns
Establish a bounded symptom-to-cause intake while implementation remains blocked.

## Use when
- A failure, regression, integration break, or runtime/performance anomaly has no fresh supported cause.

## Do not use when
- A supported cause already exists, or the task is a feature/refactor with no unexplained failure.

## Required inputs
- Request mode, neutral failure report, observable surface, source/environment identity, authority ceiling, existing patch, and protected work.

## Procedure
1. Restate the symptom without embedding a favored cause or repair.
2. Bind the stopping point to report-only, diagnosis-to-cause, or authorized repair-after-cause authority.
3. Preserve and characterize existing or concurrent work; never discard it to recreate a preferred workflow.
4. Identify the smallest real reproduction surface and separate product behavior from setup, fixture, harness, permission, and environment prerequisites.
5. Bind task-owned probe resources, side-effect ceiling, sensitive-data policy, retry budget, and cleanup proof.
6. Emit `workflow-intake` and request the mapped diagnosis decision; production edits and persistent instrumentation remain blocked until discriminating evidence supports a cause.

## Output contract
- One `workflow-intake` with symptom, observation surface, source/environment, authority, existing-work projection, probe boundary, implementation blocker, and typed diagnosis decision request.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at the diagnosis intake; never turn a plausible cause or experimental patch into a repair.
