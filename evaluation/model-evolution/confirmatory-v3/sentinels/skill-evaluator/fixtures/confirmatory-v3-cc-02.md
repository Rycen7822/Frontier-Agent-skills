# Confirmatory case D23-CC-02

Normative source: skill-evaluator/references/longitudinal-evaluation.md#Offline comparison owner
Input shape: ordinary

## Supplied facts

```json
{
  "artifacts": {
    "mode": "failure_closure",
    "other_metrics_improved": true,
    "package_change_count": 1,
    "protected_metrics_pass": true,
    "target_failure_in_A": true,
    "target_failure_in_B": true
  },
  "request": "Classify the revision without averaging away the target."
}
```

## Protected boundary

The frozen target is non-compensating.

## Semantic rubric

- centers the bound failure
- rejects compensation by unrelated improvements

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
