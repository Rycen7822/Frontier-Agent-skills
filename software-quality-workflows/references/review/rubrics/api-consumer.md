---
{
  "card_id": "sqw.review.rubrics.api-consumer",
  "card_version": 1,
  "kind": "rubric",
  "consumes": [
    "rubric_review_contract",
    "bounded_change_material",
    "api_consumer_contract"
  ],
  "produces": [
    "api_consumer_findings"
  ],
  "max_active_neighbors": 0,
  "max_bytes": 8192,
  "neighbors": []
}
---
# API Consumer Rubric

## Decision this card owns
Identify consumer-visible API or developer-experience regressions in the scoped change.

## Use when
- Public/internal APIs, schemas, CLI surfaces, SDKs, configuration, examples, or developer-facing documentation change.

## Do not use when
- The concern is solely internal implementation or requires a separate architecture/security review.

## Required inputs
- Frozen consumer contract, implementation and schema/spec, compatibility policy, examples/docs, and result-envelope contract.

## Procedure
1. Compare endpoint/command shape, methods, parameters, status and error semantics, auth, pagination, idempotency, and version behavior where applicable.
2. Check implementation, schema/spec, generated artifacts, SDK/types, documentation, and examples for one coherent contract.
3. Evaluate compatibility, deprecation, migration, defaults, and discoverability from the consumer's perspective.
4. Run or inspect executable, secret-free examples for materially changed paths; verify failure as well as success semantics.
5. Emit only line-grounded, change-caused findings with concrete consumer impact and smallest correction.

## Output contract
- Zero or more local finding candidates with affected consumer contract, evidence, compatibility/usage impact, correction, confidence, blocking, and verification.

## Load next only if

None. Return control to Router after producing the output contract.

## Stop
Stop at API-consumer evidence; do not redesign the interface or invoke another rubric.
