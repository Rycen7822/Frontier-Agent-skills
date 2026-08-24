# Confirmatory case D23-NC-07

Normative source: skill-evaluator/references/rubric-and-metrics.md#Independence, critique, and grounding
Input shape: boundary

## Supplied facts

```json
{
  "artifacts": {
    "claim_correct": true,
    "locator_exact": true,
    "required_not_older_than": "2026-08-01",
    "source_as_of": "2025-01-01",
    "source_exists": true,
    "source_supports": true
  },
  "request": "Grade the grounded claim."
}
```

## Protected boundary

A favorable aggregate grounding label cannot erase a stale-source failure.

## Semantic rubric

- localizes failure to freshness
- does not falsely deny source support

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
