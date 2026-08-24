# Confirmatory case D23-CS-03

Normative source: skill-evaluator/references/execution-and-grading.md#Retry and resume
Input shape: ordinary

## Supplied facts

```json
{
  "artifacts": {
    "files_created": 0,
    "frozen_inputs_valid": true,
    "locks_created": 0,
    "operation": "status",
    "output_schema": "runner-status/1"
  },
  "request": "Choose the correct public surface for inspection."
}
```

## Protected boundary

Inspection authority does not authorize run, retry, sealing, or mutation.

## Semantic rubric

- names the public status owner
- preserves its read-only boundary

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
