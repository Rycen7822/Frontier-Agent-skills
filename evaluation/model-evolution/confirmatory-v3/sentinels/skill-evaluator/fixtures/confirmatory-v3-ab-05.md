# Confirmatory case D23-AB-05

Normative source: skill-evaluator/references/evaluation-contract.md#Holdout and manual authority
Input shape: boundary

## Supplied facts

```json
{
  "artifacts": {
    "final_authority_status": "blocked",
    "manual_receipt": {
      "decision": "reject",
      "valid": true
    },
    "usefulness_status": "supported"
  },
  "request": "Reconcile the two results."
}
```

## Protected boundary

A later authority decision cannot mutate the evidence result.

## Semantic rubric

- states both outcomes
- does not portray their difference as inconsistency

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
