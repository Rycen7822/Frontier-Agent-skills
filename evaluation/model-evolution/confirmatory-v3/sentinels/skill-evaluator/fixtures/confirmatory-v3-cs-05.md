# Confirmatory case D23-CS-05

Normative source: skill-evaluator/references/execution-and-grading.md#Grader semantic owner
Input shape: boundary

## Supplied facts

```json
{
  "artifacts": {
    "check": {
      "check_id": "clarity",
      "pass_condition": "states the boundary"
    },
    "transport_schema_valid": true,
    "view": {
      "answer": "...",
      "evidence_path": "/tmp/run-9/raw.txt"
    }
  },
  "request": "Distinguish transport shape from semantic admissibility."
}
```

## Protected boundary

Formal payload meaning and transport shape have separate owners.

## Semantic rubric

- names the semantic rejection owner
- does not blame JSON transport shape

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
