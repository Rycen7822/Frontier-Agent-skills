# Confirmatory case D23-DV-03

Normative source: skill-evaluator/references/execution-and-grading.md#Compiler and dispositions
Input shape: ordinary

## Supplied facts

```json
{
  "artifacts": {
    "attempt_rows": 1,
    "entry": {
      "disposition": "unsupported",
      "ordinal": 9
    },
    "request_count": 1,
    "workspace_count": 1
  },
  "request": "Validate the evidence shape."
}
```

## Protected boundary

Unsupported feasibility must not be converted into an attempted task result.

## Semantic rubric

- identifies every forbidden execution artifact present
- does not score task success or failure

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
