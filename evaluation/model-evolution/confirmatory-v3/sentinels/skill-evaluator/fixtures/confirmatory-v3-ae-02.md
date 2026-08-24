# Confirmatory case D23-AE-02

Normative source: skill-evaluator/references/reporting-and-decisions.md#Exit and immutable retry
Input shape: ordinary

## Supplied facts

```json
{
  "artifacts": {
    "analysis_ready": true,
    "diagnostic_result": "complete",
    "evidence_status": "complete",
    "level": "L1",
    "usefulness_status": "not_evaluable"
  },
  "request": "Classify the analyzer exit."
}
```

## Protected boundary

L1's claim ceiling is diagnosis only.

## Semantic rubric

- states the diagnostic exception to comparative usefulness
- preserves the L1 claim ceiling

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
