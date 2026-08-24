# Confirmatory case D23-CS-04

Normative source: skill-evaluator/references/execution-and-grading.md#Runner and host protocol
Input shape: ordinary

## Supplied facts

```json
{
  "artifacts": {
    "entry_disposition": "execute",
    "execute_case_requests": 1,
    "reset_proven": true,
    "shell": false,
    "terminal_results": 1
  },
  "request": "Identify the execution owner."
}
```

## Protected boundary

The runner executes a frozen choice; it does not become the decision owner.

## Semantic rubric

- names runner responsibilities
- excludes analysis and selection authority

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
