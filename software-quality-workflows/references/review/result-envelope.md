---
{
  "card_id": "sqw.review.result-envelope",
  "card_version": 1,
  "kind": "procedure",
  "consumes": [
    "review_scope_projection",
    "finding_set",
    "coverage_projection",
    "verification_evidence",
    "spec_traceability_projection"
  ],
  "produces": [
    "local_review_result"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 4096,
  "neighbors": []
}
---
# Local Review Result Envelope

## Decision this card owns
Assemble one immutable, revision-bound local review result from observed findings, coverage, verification, and applicable specification traceability.

## Use when
- A bounded review has completed and its result must be consumed by a controller, author, fixer, or later publication check.

## Do not use when
- The work is still selecting review tier or specialist coverage.
- The decision concerns remote checks, hosted approvals, branch protection, merge, release, deploy, publish, or publication authority.

## Required inputs
- Frozen base/head/scope identity, one coverage entry per scoped path, observed findings, evidence status, traceability status and evidence when applicable, and unresolved non-finding risks.

## Procedure
1. Emit schema version `3.0` with the exact reviewed base, head, and frozen scope hash.
2. Record `code_review_verdict` as `pass`, `changes_requested`, or `inconclusive`; record verification separately as `passed`, `failed`, `partial`, or `not_run`.
3. Record specification traceability as `complete`, `partial`, `not_assessed`, or `not_applicable`, with evidence refs for complete or partial claims.
4. Include every frozen-scope path exactly once as `full`, `sampled`, or `not_reviewed`; sampled coverage requires an explicit sampling boundary.
5. Ground every finding in an allowlisted path or observable contract, reviewed revision, concrete evidence and impact, smallest safe response, confidence, verification state, and independent blocking flag.
6. Name every blocking finding in `blocking_reasons`; add concise non-finding blockers when evidence or authoritative decisions are missing.
7. A local pass may describe an honestly sampled scope, but it never implies repository-wide coverage or publication readiness.
8. Keep later finding dispositions separate; do not mutate the immutable review result after fixes or discussion.

## Output contract
- One schema-valid `local_review_result` with identity, local engineering and evidence verdicts, spec traceability, exact coverage, findings, blockers, and optional summary/positive notes.
- Never emit merge readiness, external approval, remote-host, branch-policy, release, deploy, publish, or publication-ceiling fields.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop with `inconclusive` when scope, revision, required specialist evidence, or authoritative requirement evidence is stale or insufficient; never fill a publication field from inference.
