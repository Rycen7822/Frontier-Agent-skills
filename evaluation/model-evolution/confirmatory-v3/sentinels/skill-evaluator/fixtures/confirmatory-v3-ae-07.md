# Confirmatory case D23-AE-07

Normative source: skill-evaluator/references/rubric-and-metrics.md#Five analyzer status axes
Input shape: boundary

## Supplied facts

```json
{
  "artifacts": {
    "applicability_status": "applicable",
    "evidence_status": "complete",
    "feasibility_status": "unsupported",
    "final_authority_status": "blocked",
    "usefulness_status": "not_evaluable"
  },
  "request": "Return the exit and retain all status axes."
}
```

## Protected boundary

Completeness cannot compensate for unsupported feasibility.

## Semantic rubric

- keeps feasibility and evidence axes distinct
- does not blame the task executor

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
