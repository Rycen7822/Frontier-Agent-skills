# Confirmatory case D23-AE-05

Normative source: skill-evaluator/references/reporting-and-decisions.md#Exit and immutable retry
Input shape: boundary

## Supplied facts

```json
{
  "artifacts": {
    "index_jsonl_parse": false,
    "index_readable": true,
    "report_only": true,
    "spec_valid": true
  },
  "request": "Return the process exit for the parse failure."
}
```

## Protected boundary

A CLI input failure is not a verified usefulness outcome.

## Semantic rubric

- identifies the error class
- does not invent a usefulness status from unparsed evidence

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
