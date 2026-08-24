# Confirmatory case D23-CC-07

Normative source: skill-evaluator/references/longitudinal-evaluation.md#Comparable version matrix
Input shape: boundary

## Supplied facts

```json
{
  "artifacts": {
    "fixture_digest_A": "1111",
    "fixture_digest_B": "2222",
    "package_identity_change_declared": true,
    "prior_side_rerun_under_B_contract": false
  },
  "request": "Determine whether the cycles support direct comparison."
}
```

## Protected boundary

Do not attribute fixture or environment changes to the Skill package.

## Semantic rubric

- names the changed control
- refuses package attribution

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
