# Confirmatory case D23-DV-05

Normative source: skill-evaluator/references/execution-and-grading.md#Receipt v5
Input shape: boundary

## Supplied facts

```json
{
  "artifacts": {
    "artifact_root": "runs/eval-7",
    "digest_matches_outside_bytes": true,
    "locator": "evidence/../../outside.json"
  },
  "request": "Decide whether the locator is admissible."
}
```

## Protected boundary

A correct digest never authorizes an out-of-root artifact path.

## Semantic rubric

- states both containment layers
- does not let digest equality override containment

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
