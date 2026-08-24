# Confirmatory case D23-AE-06

Normative source: skill-evaluator/references/reporting-and-decisions.md#Exit and immutable retry
Input shape: boundary

## Supplied facts

```json
{
  "artifacts": {
    "evidence_status": "incomplete",
    "invalid_attempts": 0,
    "missing_required_attempts": 1,
    "usefulness_status": "not_evaluable"
  },
  "request": "Classify the exit."
}
```

## Protected boundary

Missing evidence is not a factual outcome failure and cannot be silently imputed.

## Semantic rubric

- states exit 3 and the missing attempt
- does not score the absent attempt

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
