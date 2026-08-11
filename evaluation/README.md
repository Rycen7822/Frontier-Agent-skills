# Static Contract Gate

`scripts/evaluate_static_contracts.py` evaluates the current source tree directly. It reports the four-skill identity, versions, activation matrix, entrypoint byte budgets, model-facing paths, Markdown links, package shape, and stated limitations as readable facts.

Run from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/evaluate_static_contracts.py --check
```

The repository gate reads source directly. A named consumer can add `--output /temporary/path/report.json` for one no-overwrite diagnostic artifact. Scored and longitudinal evaluation own usefulness, behavior, and context-efficiency claims.
