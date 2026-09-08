---
name: skill-evaluator
description: Assess skill effectiveness from relevant agent history or scoped execution evidence.
metadata:
  version: 5.0.1
  author: Hermes Agent
  hosts: [codex, hermes-agent]
  hermes:
    tags: [evaluation, testing, benchmarking]
    category: software-development
    related_skills: [software-quality-workflows]
---

# Skill Evaluator

Choose the cheapest evidence that answers the requested skill decision. Resolve bundled resources through `$SKILL_EVALUATOR_DIR`, the directory containing this file.

For behavior-preserving maintenance, judge equivalence from the diff and use only relevant local checks. No history review or model call is required. Versions, hashes, timestamps and unrelated documentation do not invalidate evidence. Optional local routing:

```bash
python3 "$SKILL_EVALUATOR_DIR/scripts/evaluate.py" check --base <revision> --impact editorial
```

For historical diagnosis, use the [history guide](references/history.md) to inspect selected episodes, attribute observed problems to the relevant skill and propose the smallest justified change. History can explain failures and costs but does not by itself establish causal improvement. A diagnosis may conclude that no edit or new evaluation is needed.

For an execution gap, select affected cases and an independent oracle. Reuse valid task evidence; changed grading normally needs only grading. Use finite task and judge budgets already supplied by the task, session or suite, passing them to the runner. If no budget is available, identify that gap before creating a run or probing the Host.

```bash
python3 "$SKILL_EVALUATOR_DIR/scripts/evaluate.py" run \
  --suite author-suite.json --host host.json --output run-2 \
  --previous-report run-1/summary.json --case relevant-case \
  --task-attempt-budget 1 --judge-invocation-budget 0
```

The [maintenance guide](references/maintenance.md) covers execution, reuse, grading and recovery. Adapt the [example suite](templates/author-suite.example.json) to actual tasks and verifiers. The Host owns execution, isolation and credentials; task and judge model/effort are separate identities.

Report selected scope, supported findings, missing evidence and actual usage. `diagnostic_only` completes a maintenance evaluation without establishing general usefulness. Unknown costs remain unknown; attempts are not API requests. Pair comparisons by independent case, since repeats do not add independent samples. A saturated baseline or inconclusive interval does not authorize automatic retries or sample expansion.
