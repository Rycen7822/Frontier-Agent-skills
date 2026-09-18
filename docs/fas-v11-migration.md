# Migrating to FAS 11.0.0

FAS 11.0.0 is a breaking change for consumers of the retired review interfaces. The bundle identity moved to `frontier-engineering/11.0.0` at compatible schema epoch 9, and the 11.0.1 patch keeps that shape while correcting the scope exit codes and the treatment of declared context paths.

## Retired interfaces

These files no longer exist in the source tree, and no compatibility alias, redirect, or legacy directory replaces them:

- `code-review/schemas/review-result.schema.json`
- `code-review/schemas/publication-readiness.schema.json`
- `code-review/schemas/codex-task-result.schema.json`
- `code-review/operator/review/result-consistency.md`
- `code-review/operator/review/publication-readiness.md`
- `code-review/tests/test_quick_identity_contract.py`

The retired records mixed defect review with publication authority. The replacement expresses review only. Consumers outside this repository must stay on v10 or read the new record; the project does not maintain a shim and does not claim seamless compatibility.

## The replacement

`code-review/schemas/review-record.schema.json` is the single schema file. It defines three roots in its `$defs`: `scope` (`fas-review-scope/1`), `record` (`fas-review-record/1`) and `check_report` (`fas-review-check/1`).

`code-review/scripts/review_support.py` exposes exactly two commands:

```bash
python3 code-review/scripts/review_support.py scope --repo "$REPO" --mode workspace --path . --output "$WORK/packet"
python3 code-review/scripts/review_support.py check --repo "$REPO" --packet "$WORK/packet" --record "$WORK/review-record.json" --output "$WORK/check-report.json"
```

Scope modes are `commit` (first parent), `range` (unique merge base), `workspace` (staged, unstaged, and untracked layers kept separate) and `snapshot` (a commit, or the reserved revision `WORKTREE`). Output directories and report files must not exist yet; existing paths are never overwritten or reused. A sealed scope returns 0 when every captured source holds text, 4 when any source is non-text, oversized, or left uncaptured, and 2 without writing `scope.json` on a hard error. Declared context paths stay evidence rather than review items, and they take part in both capture and freshness.

## What a check result does and does not mean

- Exit 2 means invalid input, a failed integrity check, or a conflicting output path. Exit 4 means a valid bounded result with partial coverage, changed inputs, unresolved locations, material concerns, or failed verification. Exit 0 means only that the performed mechanical checks were satisfied.
- A structurally valid record with a `critical` finding is still only structurally valid. The checker issues no merge, release, or publication permission, and never reports that a review is current.
- Coverage entries are producer declarations about scope items. They are not proof that a model read every file, and the checker does not rewrite a record to make coverage look complete.
- Verification entries record what the producer claims to have observed. The checker does not execute them and treats a non-empty observation as no evidence that a command ran.

## Activation and environment

`software-quality-workflows` and `skill-evaluator` are explicit-only; the remaining eight skills stay implicit-eligible. The helper requires a POSIX environment, Python 3.11 or later, Git 2.41 or later, and the `jsonschema` package on the machine that runs it. Installing the plugin does not install Python packages, and the helper never installs dependencies, fetches Git objects, calls a model, or publishes results.

## Evaluation status

`evaluation/review-v11/` prepares twelve fixture cases, one compact author suite, and a model rubric with `task_attempt_budget: 0` and `judge_invocation_budget: 0`. `tests/test_review_v11_suite.py` only normalizes the suite against a stub catalog. No provider call, task attempt, or judge invocation was executed for this cut, so `model_effectiveness` remains `not_measured`.
