# Confirmatory case D23-CC-05

Normative source: skill-evaluator/references/longitudinal-evaluation.md#Offline comparison owner
Input shape: boundary

## Supplied facts

```json
{
  "artifacts": {
    "A_to_B_changed_axes": [
      "judge_identity"
    ],
    "B_to_C_changed_axes": [
      "model_identity"
    ],
    "all_other_axes_equal_per_leg": true,
    "declared_mode": "bridge"
  },
  "request": "Classify the transition design."
}
```

## Protected boundary

The two legs must not be collapsed into a single-factor A-to-C claim.

## Semantic rubric

- describes both legs
- keeps their attributions separate

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
