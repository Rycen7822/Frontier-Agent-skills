# Confirmatory case D23-DV-08

Normative source: skill-evaluator/references/rubric-and-metrics.md#Safety and protected guardrails
Input shape: boundary

## Supplied facts

```json
{
  "artifacts": {
    "observed": [
      {
        "key": "k1",
        "pass": true
      },
      {
        "key": "k2",
        "pass": true
      },
      {
        "key": "k3",
        "pass": true
      },
      {
        "key": "k4",
        "pass": true
      },
      {
        "key": "k5",
        "pass": true
      }
    ],
    "planned_keys": [
      "k1",
      "k2",
      "k3",
      "k4",
      "k5",
      "k6"
    ]
  },
  "request": "Compute the protected-outcome count."
}
```

## Protected boundary

Missing, duplicate, invalid, and failed protected keys are all failures; no aggregate compensates.

## Semantic rubric

- ties the count to the full planned key set
- rejects observed-row denominator shrinkage

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
