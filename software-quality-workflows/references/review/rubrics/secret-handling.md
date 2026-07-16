---
{
  "card_id": "sqw.review.rubrics.secret-handling",
  "card_version": 1,
  "kind": "rubric",
  "consumes": [
    "rubric_review_contract",
    "bounded_change_material",
    "credential_exposure_surface"
  ],
  "produces": [
    "secret_handling_findings"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# Secret-Handling Rubric

## Decision this card owns
Identify credential, token, cookie, key, or secret-material exposure and lifecycle regressions in the scoped change.

## Use when
- Authentication, credentials, environment/configuration, logs, fixtures, examples, screenshots, artifacts, or secret providers are affected.

## Do not use when
- The concern is broader exploit security, privacy data, or dependency provenance without secret material.

## Required inputs
- Frozen credential contract, affected source/runtime/artifact surfaces, secret-provider policy, evidence, and result-envelope contract.

## Procedure
1. Check repository content, history-sensitive changes, logs, errors, fixtures, tests, examples, screenshots, caches, and produced artifacts for secret material or unsafe identifiers.
2. Check approved provider usage, least privilege, scope, expiration, rotation/revocation, redaction, and failure-path handling.
3. Distinguish removing an exposed source value from incident response: known exposure also requires rotation/revocation and history/artifact assessment by an authorized operator.
4. Never print or copy live credentials while gathering evidence; use redacted structure and synthetic values.
5. Emit only scoped findings with exposure surface, likely consequence, immediate containment/correction, confidence, blocking, and safe verification; do not perform destructive cleanup.

## Output contract
- Zero or more local finding candidates that remain redacted and separate source correction from required credential response.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at secret-handling evidence; do not reveal secrets, rotate credentials, or rewrite history.
