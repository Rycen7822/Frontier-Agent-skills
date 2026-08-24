# Confirmatory case D23-NC-05

Normative source: skill-evaluator/references/execution-and-grading.md#Process evidence levels
Input shape: boundary

## Supplied facts

```json
{
  "artifacts": {
    "body_loaded": false,
    "cleanup_proven": false,
    "exit_zero": null,
    "receipt_parsed": false,
    "retrieved": true,
    "state_transition_proven": false
  },
  "request": "Credit successful process use from retrieval alone."
}
```

## Protected boundary

Earlier stage evidence never implies later workflow completion.

## Semantic rubric

- credits only the observed stage
- enumerates missing completion facts

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
