# Confirmatory case D23-NC-01

Normative source: skill-evaluator/references/task-suite-design.md#Frontier-model case filter
Input shape: ordinary

## Supplied facts

```json
{
  "artifacts": {
    "context_tradeoff": false,
    "package_specific_procedure": false,
    "regression_or_safety_boundary": false,
    "state_or_tool_interaction": false
  },
  "request": "Add a case asking how to reverse a list in Python."
}
```

## Protected boundary

The suite measures specialized incremental help, not generic competence.

## Semantic rubric

- identifies the absence of specialized mechanisms
- does not reward generic difficulty

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
