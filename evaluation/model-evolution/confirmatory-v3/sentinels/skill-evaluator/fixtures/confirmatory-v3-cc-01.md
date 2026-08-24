# Confirmatory case D23-CC-01

Normative source: skill-evaluator/references/longitudinal-evaluation.md#Offline comparison owner
Input shape: ordinary

## Supplied facts

```json
{
  "artifacts": {
    "bound_failure_class": "missing-cleanup",
    "mode": "failure_closure",
    "package_change_count": 1,
    "protected_metrics_pass": true,
    "target_failure_in_A": true,
    "target_failure_in_B": false
  },
  "request": "Classify the revision."
}
```

## Protected boundary

Closed is diagnostic revision evidence, not release promotion.

## Semantic rubric

- states the bound failure mechanism
- keeps closure within the frozen scope

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
