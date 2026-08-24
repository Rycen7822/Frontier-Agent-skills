# Confirmatory case D23-AE-04

Normative source: skill-evaluator/SKILL.md#Run the owners
Input shape: ordinary

## Supplied facts

```json
{
  "artifacts": {
    "manual_receipt": {
      "decision": "hold",
      "valid": true
    },
    "report_only": false,
    "usefulness_status": "supported"
  },
  "request": "Classify the exit without rewriting empirical status."
}
```

## Protected boundary

Manual authority and empirical usefulness are separate axes.

## Semantic rubric

- separates empirical and authority outcomes
- does not rewrite supported usefulness

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
