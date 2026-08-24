# Confirmatory case D23-AB-07

Normative source: skill-evaluator/references/reporting-and-decisions.md#External decision record
Input shape: boundary

## Supplied facts

```json
{
  "artifacts": {
    "artifact_hashes_match": true,
    "external_decision": "deploy",
    "requested_summary_edit": {
      "usefulness_status": "deployed"
    }
  },
  "request": "Apply the external decision."
}
```

## Protected boundary

External decisions overlay evidence; they never mutate or self-promote it.

## Semantic rubric

- recognizes external authority
- preserves immutable evidence identity

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
