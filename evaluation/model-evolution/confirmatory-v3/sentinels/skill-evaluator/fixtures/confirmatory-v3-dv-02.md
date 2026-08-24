# Confirmatory case D23-DV-02

Normative source: skill-evaluator/references/execution-and-grading.md#Compiler and dispositions
Input shape: ordinary

## Supplied facts

```json
{
  "artifacts": {
    "ready": true,
    "required_probes": [
      {
        "id": "p-network",
        "status": "unknown"
      },
      {
        "id": "p-session",
        "status": "unsupported"
      }
    ]
  },
  "request": "Choose the single plan disposition."
}
```

## Protected boundary

A capability disposition is feasibility evidence, not an outcome failure.

## Semantic rubric

- names unknown-capability precedence
- preserves the feasibility-versus-outcome boundary

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
