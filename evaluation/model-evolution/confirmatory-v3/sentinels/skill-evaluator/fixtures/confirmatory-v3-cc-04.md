# Confirmatory case D23-CC-04

Normative source: skill-evaluator/references/longitudinal-evaluation.md#Offline comparison owner
Input shape: ordinary

## Supplied facts

```json
{
  "artifacts": {
    "apparatus_equal": true,
    "changed_axes": [
      "model_tokenizer_identity"
    ],
    "declared_mode": "direct",
    "judge_policy_equal": true
  },
  "request": "Choose the transition mode and attribution ceiling."
}
```

## Protected boundary

No unregistered apparatus difference may be attributed to the model.

## Semantic rubric

- states the isolated axis
- does not infer beyond frozen observations

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
