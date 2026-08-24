# Confirmatory case D23-CS-02

Normative source: skill-evaluator/references/execution-and-grading.md#Compiler and dispositions
Input shape: ordinary

## Supplied facts

```json
{
  "artifacts": {
    "inputs_valid": true,
    "observed_process_starts": 0,
    "plan_emitted": true,
    "ready": true,
    "requested_operation": "compile"
  },
  "request": "Identify the command owner and allowed effects."
}
```

## Protected boundary

Compilation is not execution and reads no prior runtime result.

## Semantic rubric

- identifies the pure-projection owner
- does not claim task execution occurred

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
