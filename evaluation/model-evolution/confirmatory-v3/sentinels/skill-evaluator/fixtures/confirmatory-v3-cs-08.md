# Confirmatory case D23-CS-08

Normative source: skill-evaluator/references/execution-and-grading.md#Manual-review receipt
Input shape: boundary

## Supplied facts

```json
{
  "artifacts": {
    "cryptographic_verification": false,
    "decision": "approve",
    "evidence_types_closed": true,
    "receipt_relative_and_contained": true,
    "role_match": true,
    "signature": "reviewer attests"
  },
  "request": "Validate the authority input exactly."
}
```

## Protected boundary

Structural authority validation must not become a cryptographic identity claim.

## Semantic rubric

- states structural validity
- preserves the attestation-only signature boundary

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
