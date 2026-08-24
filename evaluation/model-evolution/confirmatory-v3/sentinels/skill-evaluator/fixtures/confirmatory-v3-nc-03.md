# Confirmatory case D23-NC-03

Normative source: skill-evaluator/references/task-suite-design.md#Coverage boundaries
Input shape: ordinary

## Supplied facts

```json
{
  "artifacts": {
    "attribution_evaluable": false,
    "case_role": "pure negative routing control",
    "routing_requirement_present": true
  },
  "request": "Decide whether case N enters the benefit denominator."
}
```

## Protected boundary

Control value and causal estimand eligibility are separate.

## Semantic rubric

- retains the control's diagnostic role
- excludes it from causal benefit language

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
