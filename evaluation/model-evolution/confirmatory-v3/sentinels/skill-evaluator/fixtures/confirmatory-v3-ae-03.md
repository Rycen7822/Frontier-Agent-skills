# Confirmatory case D23-AE-03

Normative source: skill-evaluator/references/reporting-and-decisions.md#Exit and immutable retry
Input shape: ordinary

## Supplied facts

```json
{
  "artifacts": {
    "evidence_status": "complete",
    "manual_decision": null,
    "report_only": false,
    "usefulness_status": "not_supported"
  },
  "request": "Return the exact process exit."
}
```

## Protected boundary

A treatment-attributable negative result must not be rewritten as apparatus invalidity.

## Semantic rubric

- states exit 1
- preserves verified negative evidence

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
