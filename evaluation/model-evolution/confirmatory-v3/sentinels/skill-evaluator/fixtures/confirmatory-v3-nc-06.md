# Confirmatory case D23-NC-06

Normative source: skill-evaluator/references/evaluation-contract.md#Holdout and manual authority
Input shape: boundary

## Supplied facts

```json
{
  "artifacts": {
    "access_controlled": false,
    "claim": "generalization",
    "payload_publicly_visible": true,
    "rehashed": false,
    "replaced": false
  },
  "request": "Use the visible example payload as the L3 holdout."
}
```

## Protected boundary

Template/example availability cannot become holdout independence.

## Semantic rubric

- names all required custody repairs
- does not claim generalization from visible bytes

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
