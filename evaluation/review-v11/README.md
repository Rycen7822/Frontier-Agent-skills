# Review v11 evaluation inputs

This directory prepares the `code-review` evaluation for FAS 11.0: twelve fixture cases, one compact author suite, and one model rubric. It is an input set, not an experiment result.

- `author-suite.json` - compact suite consumed by `skill-evaluator/scripts/author_suite.py`. It declares three treatments (`baseline/skill_disabled`, `candidate/force_loaded`, `candidate/natural_routing`), `repeats: 1`, one model grader, and `task_attempt_budget: 0` with `judge_invocation_budget: 0`.
- `rubric.md` - the grader prompt: check definitions plus the expected facts for all twelve cases.
- `fixtures/RV01` ... `fixtures/RV12` - the case seeds. Prompts reference these paths, and a Host workspace keeps the same relative layout.

The baseline treatment disables only the `code-review` skill. It does not mean "FAS not installed" or "bare Astra"; a whole-bundle comparison needs a real host configuration and its own budget, and was not run here.

[`tests/test_code_review_evaluation_suite.py`](../../tests/test_code_review_evaluation_suite.py) normalizes this suite against a stub catalog that declares `code-review`, checks the zero execution budgets, compiles the fixtures, and verifies in a temporary copy that the cache-size repair case (`RV11`) fails before the specified repair and passes after it. The seed fixtures stay unchanged: the deliberately retained defects are evaluation inputs, not product bugs.

Local validation of this directory says nothing about model quality. Every case remains unmeasured until a real Host run exists, so the current effectiveness status is `not_measured`.
