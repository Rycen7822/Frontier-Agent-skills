# Confirmatory case D23-CS-06

Normative source: skill-evaluator/references/execution-and-grading.md#Deterministic grader receipt
Input shape: boundary

## Supplied facts

```json
{
  "artifacts": {
    "exit_code": 0,
    "invocation_bound": true,
    "stdout_single_json": true,
    "verifier_available": true
  },
  "request": "Recompute the result by importing the verifier."
}
```

## Protected boundary

Analysis consumes immutable evidence and does not regenerate it.

## Semantic rubric

- explains evidence consumption
- rejects evidence regeneration

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
