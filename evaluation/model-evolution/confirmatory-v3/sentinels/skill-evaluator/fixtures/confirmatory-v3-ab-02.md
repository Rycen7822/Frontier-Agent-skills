# Confirmatory case D23-AB-02

Normative source: skill-evaluator/references/reporting-and-decisions.md#Status model
Input shape: ordinary

## Supplied facts

```json
{
  "artifacts": {
    "final_authority_status": "blocked",
    "manual_gate_required": true,
    "manual_receipt_present": false,
    "usefulness_status": "supported"
  },
  "request": "State whether the package should now be deployed."
}
```

## Protected boundary

Supported is not promotion.

## Semantic rubric

- reports both axes exactly
- does not convert supported into deployment advice

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
