# Confirmatory case D23-CS-07

Normative source: skill-evaluator/references/longitudinal-evaluation.md#Offline comparison owner
Input shape: boundary

## Supplied facts

```json
{
  "artifacts": {
    "capsule_count": 2,
    "capsule_digests_match": true,
    "comparison_kind": "performance_tournament",
    "plan_schema": 3
  },
  "request": "Run the offline comparator."
}
```

## Protected boundary

Offline comparison classification is narrower than general benchmarking orchestration.

## Semantic rubric

- states the finite accepted kind set
- does not expand comparator effects

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
