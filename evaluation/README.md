# Static Contract Gate

`scripts/evaluate_static_contracts.py` evaluates the current source tree directly. It reports the four-skill identity, versions, activation matrix, entrypoint byte budgets, model-facing paths, Markdown links, package shape, and stated limitations as readable facts.

Run from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/evaluate_static_contracts.py --check
```

The `review-v11/` directory holds the prepared code-review evaluation inputs: twelve fixture cases, one compact author suite with a single model grader, and the rubric that defines its checks. The suite is validated locally by `tests/test_review_v11_suite.py`, which only normalizes the suite against a stub catalog. No provider, task-attempt or judge call was executed for this cut, so every fixture's model effectiveness remains unmeasured.

The repository gate reads source directly. A named consumer can add `--output /temporary/path/report.json` for one no-overwrite diagnostic artifact. Scored and longitudinal evaluation own usefulness, behavior, and context-efficiency claims.
