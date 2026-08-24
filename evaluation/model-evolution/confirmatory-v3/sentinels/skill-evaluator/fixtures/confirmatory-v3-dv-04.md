# Confirmatory case D23-DV-04

Normative source: skill-evaluator/references/execution-and-grading.md#Run index v3
Input shape: ordinary

## Supplied facts

```json
{
  "artifacts": {
    "actual_plan_sha256": "aaaa",
    "index_records": [
      {
        "plan_digest": "bbbb",
        "record_type": "index_header"
      },
      {
        "receipt": {
          "digest": "cccc",
          "path": "r.json"
        },
        "record_type": "attempt"
      }
    ]
  },
  "request": "Verify index custody."
}
```

## Protected boundary

Semantic identity and exact-byte custody remain separate contracts.

## Semantic rubric

- locates the mismatch in the header binding
- does not accept matching readable IDs as custody

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
