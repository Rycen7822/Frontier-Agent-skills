# Confirmatory case D23-DV-07

Normative source: skill-evaluator/references/execution-and-grading.md#Context receipt
Input shape: boundary

## Supplied facts

```json
{
  "artifacts": {
    "context_usage": {
      "bytes": 0,
      "components": [],
      "controlled_bytes": 0,
      "controlled_core_bytes": 0,
      "status": "captured"
    }
  },
  "request": "Classify attribution coverage."
}
```

## Protected boundary

Zero measured context and absent measurement are distinct facts.

## Semantic rubric

- clearly distinguishes zero from missing
- preserves attribution coverage

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
