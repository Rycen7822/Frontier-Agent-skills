# Confirmatory case D23-CC-06

Normative source: skill-evaluator/references/reporting-and-decisions.md#Offline comparison report v3
Input shape: boundary

## Supplied facts

```json
{
  "artifacts": {
    "bridge_available": false,
    "changed_axes": [
      "model_identity",
      "harness_identity"
    ],
    "declared_mode": "combined"
  },
  "request": "State the strongest valid attribution."
}
```

## Protected boundary

Combined drift never becomes single-factor attribution.

## Semantic rubric

- uses joint-drift language
- expressly refuses single-factor attribution

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
