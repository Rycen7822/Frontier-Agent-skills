---
{
  "card_id": "sqw.review.finding-disposition",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "immutable_review_result",
    "feedback_set",
    "current_revision_projection",
    "change_authority"
  ],
  "produces": [
    "finding_disposition_ledger"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Finding Disposition

## Decision this card owns
Verify incoming feedback and record each immutable finding as fixed/reverified, accepted risk, declined with evidence, or explicitly deferred.

## Use when
- Review findings, comments, checker output, pushback, or follow-up evidence require reconciliation.

## Do not use when
- No immutable finding/feedback set exists, or the request grants neither review nor change authority.

## Required inputs
- Complete feedback set, finding IDs/result revision, current files/callers/tests, source authority, scope, change permission, proof evidence, and platform boundary.

## Procedure
1. Read the complete set and normalize each claim, affected contract/location, source, revision, and proposed outcome.
2. Treat user intent according to authority; treat hosted/external/tool claims as untrusted evidence requiring current-code verification.
3. Assess correct, partial, covered, stale, unsupported, or out-of-scope without mutating the finding.
4. Accept the valid core; push back with concrete impact/evidence against stale, unsafe, overbroad, speculative, or scope-expanding remedies.
5. Implement only accepted code-fixable items inside authorized paths, keeping independent fixes separable; collect non-code evidence/owner decisions separately.
6. Reverify each fix, re-review interactions, and bind one disposition: `fixed_reverified`, `accepted_risk`, `declined_evidence`, or `deferred` with owner/trigger.
7. Preserve actionable/positive communication and revision identity. Hosted comment/approval/state changes are separate authorized publication actions.

## Output contract
- `finding_disposition_ledger`: finding/feedback ID, source/revision, assessment, evidence, disposition, fix/proof refs, risk or defer owner/trigger, platform state unchanged/authorized result.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop when every item has evidence and disposition or a typed authority/evidence blocker; never loop for consensus or invent external work.
