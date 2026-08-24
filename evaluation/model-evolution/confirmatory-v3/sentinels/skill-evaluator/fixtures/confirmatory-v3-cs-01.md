# Confirmatory case D23-CS-01

Normative source: skill-evaluator/references/evaluation-contract.md#Spec v7 owner
Input shape: ordinary

## Supplied facts

```json
{
  "artifacts": {
    "grader": {
      "grader_id": "det-7",
      "type": "deterministic"
    },
    "requirement": {
      "grader_id": "det-7",
      "owner": "model"
    },
    "schema_shape_valid": true
  },
  "request": "Name the owner and validation result."
}
```

## Protected boundary

Schema-shape success cannot certify cross-field or cross-file semantics.

## Semantic rubric

- names both owners and their distinct jobs
- does not treat schema validity as semantic validity

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
