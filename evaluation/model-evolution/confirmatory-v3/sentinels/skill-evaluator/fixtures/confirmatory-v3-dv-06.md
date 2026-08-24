# Confirmatory case D23-DV-06

Normative source: skill-evaluator/references/execution-and-grading.md#Deterministic grader receipt
Input shape: boundary

## Supplied facts

```json
{
  "artifacts": {
    "exit_code": 1,
    "selected_check_ids": [
      "c1"
    ],
    "stderr": "",
    "stdout": {
      "checks": [
        {
          "check_id": "c1",
          "pass": true
        }
      ],
      "overall_pass": true
    }
  },
  "request": "Validate the deterministic grader receipt."
}
```

## Protected boundary

Deterministic evidence remains factual and is not rescored by a model rubric.

## Semantic rubric

- describes the exact disagreement
- does not reinterpret the verifier's factual result

## Response contract

Return one JSON object and no prose wrapper with exactly these fields: `case_id`, `owner`, `oracle_result`, `disposition`, `boundary_preserved`, and `rationale`. Derive the owner and oracle result from the supplied facts and normative contract.
