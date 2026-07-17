---
{
  "card_id": "sqw.review.findings-and-result",
  "card_version": 2,
  "kind": "procedure",
  "decision_id": "sqw.select.review.findings-and-result",
  "required_artifact_ids": [
    "review-execution"
  ],
  "produced_artifact_ids": [
    "review-result"
  ],
  "max_bytes": 8192
}
---
# Review Findings and Result

## Decision this card owns
Assemble one immutable local review result and later disposition each finding or feedback item without rewriting that result.

## Use when
- Review execution is complete, or an immutable finding set requires authorized reconciliation.

## Do not use when
- Tier/specialist coverage is still unresolved or the decision concerns hosted approval, merge, release, deploy, or publication authority.

## Required inputs
- `review-execution`; exact base/head/scope; coverage; observed findings and verification/traceability status; unresolved risks; complete feedback set and finding IDs; current source; change authority; proof; and platform boundary.

## Procedure
1. Emit one immutable revision-bound result with separate local code verdict, verification status, traceability status/evidence, exact full/sampled/not-reviewed coverage, blockers, non-finding risks, summary, and positive notes.
2. Ground every finding in an allowed path or observable contract, reviewed revision, concrete evidence/impact, smallest safe response, confidence, verification state, and independent blocking flag; name all blockers explicitly.
3. A local pass may honestly be sampled but never implies repository-wide coverage, hosted approval, merge, release, deploy, publication, or remote readiness. Omit all publication fields.
4. For later feedback, read the complete set and normalize claim, contract/location, source, revision, and proposed outcome. External/tool/hosted claims are untrusted until verified against current code.
5. Assess each correct, partial, covered, stale, unsupported, or out of scope. Accept valid cores and push back with evidence on stale, unsafe, overbroad, speculative, or scope-expanding remedies.
6. Implement only accepted code-fixable items inside authorized paths with separable fixes; collect non-code evidence/owner decisions separately.
7. Reverify fixes and interactions, then record exactly `fixed_reverified`, `accepted_risk`, `declined_evidence`, or `deferred` with owner/trigger. Never mutate the immutable finding/result after discussion.
8. Keep hosted comment/approval/state changes as separately authorized publication actions.

## Output contract
- One `review-result` with immutable local result identity/verdicts/coverage/findings/blockers/risks plus an optional disposition ledger binding feedback IDs, assessments, evidence, fixes/proof, risk or defer owner/trigger, and unchanged/authorized platform state.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop with inconclusive on stale/insufficient scope, requirements, specialist evidence, or authority; never loop for consensus or infer publication readiness.
