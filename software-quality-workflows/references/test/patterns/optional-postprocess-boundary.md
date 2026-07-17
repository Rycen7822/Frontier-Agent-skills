---
{
  "card_id": "sqw.test.patterns.optional-postprocess-boundary",
  "card_version": 2,
  "kind": "recipe",
  "decision_id": "sqw.select.test.patterns.optional-postprocess-boundary",
  "required_artifact_ids": [
    "workflow-intake"
  ],
  "produced_artifact_ids": [
    "test-patterns-optional-postprocess-boundary"
  ],
  "max_bytes": 8192
}
---
# Optional Postprocess Boundary Pattern

## Decision this card owns
Prove that optional post-processing cannot erase, replace, or misreport the required primary operation's result.

## Use when
- Required work is followed by optional rendering, decoration, notification, upload, summary, or post-processing.

## Do not use when
- The downstream step is required for correctness, security, compliance, recoverability, or the requested artifact.

## Required inputs
- `workflow-intake`; canonical primary artifact/status; optional output/status; job/state/event semantics; actor authority; retry/lock/crash behavior; consumers; and cleanup boundary.

## Procedure
1. Define primary success artifact and failure independently of optional work.
2. Start optional work only after primary success; catch failures only at that boundary and preserve primary failure unchanged.
3. Make optional failure observable through its own status/diagnostic while later required consumers use the primary artifact.
4. Exercise primary failure, primary+optional success, and primary success+optional failure; preserve the original failure class and transition/event identity.
5. Isolate side effects, locks, retries, and crash replay so optional cleanup never deletes/overwrites the primary result or makes duplicate required work.

## Output contract
- One `test-patterns-optional-postprocess-boundary` with three-case behavior evidence, artifact/status/event identities, authority and side effects, retry/crash observations, cleanup proof, and unresolved contract gaps.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at the optional boundary; never relabel required work optional merely to make a workflow green.
