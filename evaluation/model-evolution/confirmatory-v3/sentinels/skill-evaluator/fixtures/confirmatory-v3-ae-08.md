# Confirmatory case D23-AE-08

Normative source: skill-evaluator/SKILL.md#Run the owners
Input shape: boundary

## Supplied facts

```json
{
  "artifacts": {
    "native_exit_cases": [
      {
        "exit": 1,
        "label": "verified-negative"
      },
      {
        "exit": 2,
        "label": "contract-error"
      },
      {
        "exit": 3,
        "label": "incomplete"
      }
    ],
    "report_only": true
  },
  "request": "Apply report-only exactly."
}
```

## Protected boundary

Report-only changes process signaling, not evidence or semantic statuses.

## Semantic rubric

- reports the complete ordered mapping
- states that statuses are not rewritten

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
