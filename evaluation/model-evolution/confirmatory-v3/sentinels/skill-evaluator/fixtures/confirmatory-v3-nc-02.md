# Confirmatory case D23-NC-02

Normative source: skill-evaluator/references/execution-and-grading.md#Routing, composition, and usage
Input shape: ordinary

## Supplied facts

```json
{
  "artifacts": {
    "expected": {
      "applied": [],
      "loaded": [],
      "selected": []
    },
    "observed": {
      "applied": [],
      "loaded": [],
      "selected": []
    }
  },
  "request": "Score the routing cell."
}
```

## Protected boundary

Routing is checked against the exact expected cell, not a target-presence proxy.

## Semantic rubric

- calls the no-match legitimate
- avoids target-presence scoring

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
