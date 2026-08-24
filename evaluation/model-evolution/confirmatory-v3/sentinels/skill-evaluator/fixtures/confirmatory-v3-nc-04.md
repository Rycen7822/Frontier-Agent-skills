# Confirmatory case D23-NC-04

Normative source: skill-evaluator/references/task-suite-design.md#Protected controls
Input shape: ordinary

## Supplied facts

```json
{
  "artifacts": {
    "attribution_evaluable": false,
    "required_execution_profile_count": 2,
    "required_outcome_requirements": 1,
    "required_profiles_present": true,
    "tags": [
      "protected"
    ]
  },
  "request": "Validate the protected case shape."
}
```

## Protected boundary

Do not invent a new case-role framework or filter missing rows from the protected denominator.

## Semantic rubric

- explains why attribution is false
- preserves full protected coverage

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
